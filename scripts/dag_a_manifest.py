#!/usr/bin/env python3
"""
Export YAML manifest(s) for Airflow DAGs (parsed from ``dags/`` via DagBag).

Single DAG (writes to ``-o`` path; default if omitted is repo root ``dag_a_manifest.yaml``):

    python scripts/dag_a_manifest.py --dag-id dag_a -o my_dag.yaml

All DAGs that parse successfully (one file per DAG + ``index.yaml``):

    python scripts/dag_a_manifest.py --all-dags --output-dir dag_manifests

Docker (pipe script into scheduler; ``scripts/`` is not mounted by default):

    Get-Content scripts/dag_a_manifest.py | docker compose exec -T airflow-scheduler python - --all-dags --output-dir /tmp/m
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import re
import subprocess
import sys
import warnings
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

DEFAULT_DAG_ID = "dag_a"
ROOT_GROUP_KEY = "__root__"
FORMAT_VERSION = 1


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _safe_filename(dag_id: str) -> str:
    return re.sub(r'[<>:"/\\\\|?*]', "_", dag_id)


def _task_group_path(task) -> list[str] | None:
    parts: list[str] = []
    tg = getattr(task, "task_group", None)
    while tg is not None:
        if getattr(tg, "is_root", False):
            break
        gid = getattr(tg, "group_id", None)
        if gid:
            parts.append(str(gid))
        tg = getattr(tg, "parent_group", None)
    return list(reversed(parts)) if parts else None


def _local_task_id_against_group(task_id: str, group_full_id: str) -> str:
    if not group_full_id:
        return task_id
    prefix = group_full_id + "."
    if task_id.startswith(prefix):
        return task_id[len(prefix) :]
    return task_id


def _registry_key(task) -> str:
    path = _task_group_path(task) or []
    full = ".".join(path) if path else ""
    return ROOT_GROUP_KEY if full == "" else full


def _task_group_context(task) -> dict[str, Any]:
    path = _task_group_path(task) or []
    full = ".".join(path) if path else None
    parent_full = ".".join(path[:-1]) if len(path) > 1 else None
    return {
        "registry_key": _registry_key(task),
        "task_group": full,
        "local_task_id": _local_task_id_against_group(task.task_id, full or ""),
        "task_group_path": path,
        "parent_task_group": parent_full,
    }


def safe_yaml_value(obj: Any, depth: int = 0) -> Any:
    if depth > 12:
        return "<max-depth>"

    if isinstance(obj, Enum):
        val = getattr(obj, "value", None)
        return val if val is not None else str(obj)

    if obj is None or isinstance(obj, (bool, int, float)):
        return obj

    if isinstance(obj, str):
        return obj

    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")

    if isinstance(obj, datetime):
        if obj.tzinfo:
            return obj.isoformat()
        return obj.replace(tzinfo=timezone.utc).isoformat()

    if isinstance(obj, date) and not isinstance(obj, datetime):
        return obj.isoformat()

    if isinstance(obj, timedelta):
        return str(obj)

    if isinstance(obj, (set, frozenset)):
        return sorted(safe_yaml_value(x, depth + 1) for x in obj)

    if isinstance(obj, Mapping):
        return {str(k): safe_yaml_value(v, depth + 1) for k, v in obj.items()}

    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [safe_yaml_value(x, depth + 1) for x in obj]

    if callable(obj):
        name = getattr(obj, "__name__", repr(obj))
        return f"<callable {name}>"

    if hasattr(obj, "serialize") and callable(obj.serialize):
        try:
            return safe_yaml_value(obj.serialize(), depth + 1)
        except Exception:
            pass

    return str(obj)


def yaml_scrub(obj: Any, depth: int = 0) -> Any:
    if depth > 20:
        return "<max-depth>"

    if isinstance(obj, Enum):
        val = getattr(obj, "value", None)
        return val if val is not None else str(obj)

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, datetime):
        return obj.isoformat() if obj.tzinfo else obj.replace(tzinfo=timezone.utc).isoformat()

    if isinstance(obj, date):
        return obj.isoformat()

    if isinstance(obj, timedelta):
        return str(obj)

    if isinstance(obj, Mapping):
        return {str(k): yaml_scrub(v, depth + 1) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [yaml_scrub(x, depth + 1) for x in obj]

    if isinstance(obj, (set, frozenset)):
        return sorted((yaml_scrub(x, depth + 1) for x in obj), key=str)

    return str(obj)


def _topological_order_ids(dag) -> list[str]:
    if hasattr(dag, "topological_sort"):
        return [t.task_id for t in dag.topological_sort()]
    raise RuntimeError("DAG has no topological_sort(); cannot compute execution order")


def execution_layers(task_ids: set[str], task_dict: dict) -> list[list[str]]:
    completed: set[str] = set()
    layers: list[list[str]] = []
    remaining = set(task_ids)

    while remaining:
        ready = sorted(
            tid
            for tid in remaining
            if task_dict[tid].upstream_task_ids <= completed
        )
        if not ready:
            raise ValueError("Cycle detected or invalid DAG graph")
        layers.append(ready)
        completed.update(ready)
        remaining -= set(ready)

    return layers


def execution_layers_within_group(task_ids: set[str], task_dict: dict) -> list[list[str]]:
    completed: set[str] = set()
    layers: list[list[str]] = []
    remaining = set(task_ids)

    while remaining:
        ready = sorted(
            tid
            for tid in remaining
            if task_dict[tid].upstream_task_ids & task_ids <= completed
        )
        if not ready:
            raise ValueError("Cycle detected within task group subset")
        layers.append(ready)
        completed.update(ready)
        remaining -= set(ready)

    return layers


def _consecutive_registry_segments(topo: list[str], task_dict: dict) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    current_key: str | None = None
    current_ids: list[str] = []

    for tid in topo:
        key = _registry_key(task_dict[tid])
        if key != current_key:
            if current_key is not None:
                runs.append({"registry_key": current_key, "task_ids": list(current_ids)})
            current_key = key
            current_ids = [tid]
        else:
            current_ids.append(tid)

    if current_key is not None:
        runs.append({"registry_key": current_key, "task_ids": list(current_ids)})
    return runs


def build_execution_order(
    topo: list[str], task_dict: dict
) -> dict[str, Any]:
    segments_out: list[dict[str, Any]] = []
    for seg_idx, seg in enumerate(_consecutive_registry_segments(topo, task_dict)):
        rk = seg["registry_key"]
        tids = set(seg["task_ids"])
        waves = execution_layers_within_group(tids, task_dict)
        entry: dict[str, Any] = {
            "segment_index": seg_idx,
            "registry_key": rk,
            "task_group_id": None if rk == ROOT_GROUP_KEY else rk,
            "local_execution_waves": [
                {"wave": w, "parallel_tasks": wave} for w, wave in enumerate(waves)
            ],
        }
        segments_out.append(entry)

    return {
        "description": (
            "Segments follow global topological order; a new segment starts when "
            "registry_key changes. local_execution_waves use only in-segment dependencies "
            "(same wave may run in parallel). For edges between segments see each task "
            "under tasks.<task_id>.upstream_task_ids and global_topological_order."
        ),
        "segments": segments_out,
    }


def _light_prune_task_meta(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in meta.items():
        if val is None:
            continue
        if key.startswith("doc_") and val in ("", {}, []):
            continue
        if key == "task_group" and isinstance(val, Mapping):
            val = {k: v for k, v in val.items() if k != "repr"}
            if not val:
                continue
        out[key] = val
    return out


def _collect_operator_call_args(task) -> dict[str, Any] | None:
    cls = type(task)
    names: list[str] = []
    if hasattr(cls, "template_fields") and cls.template_fields:
        names.extend(cls.template_fields)
    for extra in ("python_callable", "python_callable_name"):
        if extra not in names:
            names.append(extra)

    out: dict[str, Any] = {}
    seen: set[str] = set()
    for name in names:
        if not name or name in seen or name.startswith("_"):
            continue
        seen.add(name)
        if not hasattr(task, name):
            continue
        try:
            val = getattr(task, name)
        except AttributeError:
            continue
        try:
            sv = safe_yaml_value(val)
        except Exception as exc:  # noqa: BLE001
            sv = f"<error serializing: {exc}>"
        if name == "templates_dict" and sv in (None, {}, []):
            continue
        out[name] = sv

    return out if out else None


def _order_task_fields(meta: dict[str, Any]) -> dict[str, Any]:
    priority = (
        "task_id",
        "task_type",
        "operator_class",
        "trigger_rule",
        "weight_rule",
        "upstream_task_ids",
        "downstream_task_ids",
        "placement",
        "operator_call_args",
        "task_group_path",
    )
    ordered: dict[str, Any] = {}
    for k in priority:
        if k in meta:
            ordered[k] = meta[k]
    for k, v in meta.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def _collect_task_metadata_full(task) -> dict[str, Any]:
    fields = task.get_serialized_fields() if hasattr(task, "get_serialized_fields") else frozenset()
    out: dict[str, Any] = {}

    for name in sorted(fields):
        if name.startswith("_"):
            continue
        try:
            val = getattr(task, name)
        except AttributeError:
            continue
        try:
            if name == "task_group" and val is not None:
                out["task_group"] = {
                    "group_id": getattr(val, "group_id", None),
                }
                continue
            out[name] = safe_yaml_value(val)
        except Exception as exc:  # noqa: BLE001
            out[name] = f"<error serializing: {exc}>"

    out["upstream_task_ids"] = sorted(task.upstream_task_ids)
    out["downstream_task_ids"] = sorted(task.downstream_task_ids)
    ctx = _task_group_context(task)
    out["placement"] = ctx

    path = _task_group_path(task)
    if path is not None:
        out["task_group_path"] = path

    cls = type(task)
    if hasattr(cls, "template_fields"):
        out["template_fields"] = list(cls.template_fields)
    if hasattr(cls, "template_ext"):
        out["template_ext"] = list(cls.template_ext)

    out["operator_class"] = f"{cls.__module__}.{cls.__qualname__}"

    call_args = _collect_operator_call_args(task)
    if call_args:
        out["operator_call_args"] = call_args
        for k in call_args:
            if k in out and k != "operator_call_args":
                out.pop(k, None)

    return _order_task_fields(_light_prune_task_meta(out))


def _collect_dag_summary(dag) -> dict[str, Any]:
    out: dict[str, Any] = {
        "dag_id": dag.dag_id,
        "fileloc": getattr(dag, "filepath", None) or getattr(dag, "fileloc", None),
        "schedule": safe_yaml_value(getattr(dag, "schedule", None)),
        "tags": sorted(dag.tags) if getattr(dag, "tags", None) else [],
        "catchup": getattr(dag, "catchup", None),
    }
    if hasattr(dag, "start_date") and dag.start_date is not None:
        out["start_date"] = safe_yaml_value(dag.start_date)
    da = getattr(dag, "default_args", None)
    if da:
        out["default_args"] = safe_yaml_value(da)
    return {k: v for k, v in out.items() if v not in (None, [], {})}


def collect_cross_dag_edges(dag) -> list[dict[str, Any]]:
    """
    Dependencies from this DAG to *other* DAG ids (sensors, triggers, etc.).
    """
    edges: list[dict[str, Any]] = []
    src = dag.dag_id

    for tid, t in dag.task_dict.items():
        ext = getattr(t, "external_dag_id", None)
        if ext is not None and str(ext) != str(src):
            edges.append(
                {
                    "relation": "external_task_sensor_or_marker",
                    "operator_type": type(t).__name__,
                    "from_dag_id": src,
                    "from_task_id": tid,
                    "to_dag_id": safe_yaml_value(ext),
                    "to_task_id": safe_yaml_value(getattr(t, "external_task_id", None)),
                    "to_task_group_id": safe_yaml_value(getattr(t, "external_task_group_id", None)),
                }
            )

        trig = getattr(t, "trigger_dag_id", None)
        if trig is not None and str(trig) != str(src):
            edges.append(
                {
                    "relation": "trigger_dag_run",
                    "operator_type": type(t).__name__,
                    "from_dag_id": src,
                    "from_task_id": tid,
                    "to_dag_id": safe_yaml_value(trig),
                }
            )

    return edges


def _silence_import_noise() -> None:
    warnings.filterwarnings("ignore")
    for name in (
        "airflow",
        "airflow.task",
        "airflow.dag_processing",
        "alembic",
        "alembic.runtime",
        "sqlalchemy",
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    logging.getLogger().setLevel(logging.CRITICAL)


def _warnings_for_dag_file(dag, import_errors: dict[str, str]) -> list[str]:
    if not import_errors:
        return []
    loc = getattr(dag, "filepath", None) or getattr(dag, "fileloc", None)
    if not loc:
        return []
    return [f"{p}: {e[:500]}" for p, e in import_errors.items() if p == loc]


def run_airflow_cli_dags_list_json() -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    Parse ``airflow dags list -o json`` (log lines may precede the JSON array).
    """
    try:
        r = subprocess.run(
            ["airflow", "dags", "list", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)

    combined = (r.stdout or "") + "\n" + (r.stderr or "")
    # First `[` can appear inside log text; JSON array of objects starts with `[{`
    m = re.search(r"\[\s*\{", combined)
    if not m:
        return None, "no JSON array in airflow dags list output"
    try:
        data = json.loads(combined[m.start() :])
    except json.JSONDecodeError as e:
        return None, str(e)
    if not isinstance(data, list):
        return None, "dags list JSON is not a list"
    return data, None


def pick_cli_row_for_dag(dag, rows: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Pick CLI list row matching this DAG (prefer same fileloc)."""
    if not rows:
        return None
    did = dag.dag_id
    loc = getattr(dag, "filepath", None) or getattr(dag, "fileloc", None)
    candidates = [r for r in rows if r.get("dag_id") == did]
    if not candidates:
        return None
    if loc:
        for r in candidates:
            if r.get("fileloc") == loc:
                return r
    return candidates[0]


def build_manifest_dict(
    dag,
    *,
    import_errors: dict[str, str] | None,
    dag_cli_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """Single-DAG manifest structure."""
    task_dict = dag.task_dict
    task_ids = set(task_dict.keys())

    topo = _topological_order_ids(dag)
    global_layers = execution_layers(task_ids, task_dict)

    tasks_full: dict[str, Any] = {}
    for tid in topo:
        tasks_full[tid] = _collect_task_metadata_full(task_dict[tid])

    warn_list = _warnings_for_dag_file(dag, import_errors or {})

    out: dict[str, Any] = {
        "manifest": {
            "dag_id": dag.dag_id,
            "format_version": FORMAT_VERSION,
            "kind": "airflow_dag_manifest",
            "warnings": warn_list or None,
        },
        "dag": _collect_dag_summary(dag),
        "global_topological_order": list(topo),
        "global_execution_waves": [
            {"wave": i, "parallel_tasks": layer} for i, layer in enumerate(global_layers)
        ],
        "execution_order": build_execution_order(topo, task_dict),
        "tasks": tasks_full,
        "cross_dag_edges_from_this_dag": collect_cross_dag_edges(dag),
    }

    if dag_cli_row:
        out["airflow_cli_dag_row"] = dag_cli_row

    return out


def build_manifest(dag_id: str) -> dict[str, Any]:
    _silence_import_noise()
    _sink = io.StringIO()
    with contextlib.redirect_stdout(_sink), contextlib.redirect_stderr(_sink):
        from airflow.models import DagBag

        dagbag = DagBag(include_examples=False)
        dag = dagbag.get_dag(dag_id)

        if dag is None:
            known = sorted(dagbag.dags.keys())
            raise SystemExit(
                f"ERROR: DAG {dag_id!r} not found. Known DAGs (sample): {known[:40]}"
            )

        cli_rows, _cli_err = run_airflow_cli_dags_list_json()
        cli_row = pick_cli_row_for_dag(dag, cli_rows)

        return build_manifest_dict(dag, import_errors=dagbag.import_errors, dag_cli_row=cli_row)


def export_all_dags(output_dir: Path) -> None:
    _silence_import_noise()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    _sink = io.StringIO()
    with contextlib.redirect_stdout(_sink), contextlib.redirect_stderr(_sink):
        from airflow.models import DagBag

        dagbag = DagBag(include_examples=False)

    cli_rows, cli_err = run_airflow_cli_dags_list_json()

    all_edges: list[dict[str, Any]] = []
    exported: list[str] = []
    files_written: list[str] = []

    for dag_id in sorted(dagbag.dags.keys()):
        dag = dagbag.get_dag(dag_id)
        if dag is None:
            continue
        cli_row = pick_cli_row_for_dag(dag, cli_rows)
        manifest = build_manifest_dict(
            dag,
            import_errors=dagbag.import_errors,
            dag_cli_row=cli_row,
        )
        all_edges.extend(manifest.get("cross_dag_edges_from_this_dag", []))

        fname = _safe_filename(dag_id) + ".yaml"
        out_path = output_dir / fname
        text = _trim_leading_non_yaml(_dump_yaml(manifest))
        out_path.write_text(text, encoding="utf-8")
        exported.append(dag_id)
        files_written.append(str(out_path))

    # Filter CLI rows to exported DAG ids only; dedupe (Airflow may list a DAG twice per bundle)
    cli_subset: list[dict[str, Any]] | None = None
    if cli_rows:
        exported_set = set(exported)
        seen_cli: set[tuple[Any, ...]] = set()
        cli_subset = []
        for r in cli_rows:
            if r.get("dag_id") not in exported_set:
                continue
            key = (r.get("dag_id"), r.get("fileloc"), r.get("bundle_name"))
            if key in seen_cli:
                continue
            seen_cli.add(key)
            cli_subset.append(r)

    index_doc: dict[str, Any] = {
        "manifest": {
            "format_version": FORMAT_VERSION,
            "kind": "airflow_manifest_index",
        },
        "export": {
            "output_dir": str(output_dir),
            "dag_ids": exported,
            "files": files_written,
        },
        "dag_dependencies_across_dags": {
            "description": (
                "Edges from tasks in one DAG that reference another DAG id "
                "(ExternalTaskSensor, TriggerDagRunOperator, etc.)."
            ),
            "edges": sorted(all_edges, key=lambda e: (e.get("from_dag_id", ""), e.get("from_task_id", ""))),
        },
        "airflow_cli": {
            "dags_list_json_subset_for_exported_dags": cli_subset,
            "dags_list_json_error": cli_err,
            "commands": ["airflow dags list -o json"],
        },
        "dagbag_import_errors": dagbag.import_errors or None,
    }

    index_path = output_dir / "index.yaml"
    index_path.write_text(_trim_leading_non_yaml(_dump_yaml(index_doc)), encoding="utf-8")
    print(str(index_path))


def verify_operator_call_args(dag_id: str) -> int:
    _silence_import_noise()
    _sink = io.StringIO()
    with contextlib.redirect_stdout(_sink), contextlib.redirect_stderr(_sink):
        from airflow.models import DagBag

        bag = DagBag(include_examples=False)
        dag = bag.get_dag(dag_id)

    if dag is None:
        print(f"FAIL: DAG {dag_id!r} not found", file=sys.stderr)
        return 1

    td = dag.task_dict
    required = ("branch_bash_ok", "branch_bash_else", "hello_add")
    missing = [t for t in required if t not in td]
    if missing:
        print(
            f"FAIL: --verify needs tasks {required}; missing {missing} (try --dag-id dag_a)",
            file=sys.stderr,
        )
        return 1

    try:
        bash_args = _collect_operator_call_args(td["branch_bash_ok"])
        assert bash_args is not None, "branch_bash_ok: missing operator_call_args"
        assert "bash_command" in bash_args, bash_args
        assert "positive" in str(bash_args["bash_command"]), bash_args["bash_command"]

        bash_else = _collect_operator_call_args(td["branch_bash_else"])
        assert bash_else and "negative" in str(bash_else.get("bash_command", "")), bash_else

        py_args = _collect_operator_call_args(td["hello_add"])
        assert py_args is not None, "hello_add: missing operator_call_args"
        assert py_args.get("op_kwargs") == {"x": 10, "y": 32}, py_args
    except (AssertionError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "OK: BashOperator bash_command and PythonOperator op_kwargs "
        "match expectations for this DAG."
    )
    return 0


def _trim_leading_non_yaml(text: str) -> str:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("manifest:") or stripped.startswith("---"):
            return "\n".join(lines[i:]) + ("\n" if text.endswith("\n") else "")
    return text


def _dump_yaml(data: dict[str, Any]) -> str:
    try:
        import yaml
    except ImportError as e:
        raise SystemExit(
            "PyYAML is required for YAML output. Install with: pip install pyyaml"
        ) from e

    cleaned = yaml_scrub(data)

    return yaml.safe_dump(
        cleaned,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=2000,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export DAG manifest(s) as YAML")
    parser.add_argument("--dag-id", default=DEFAULT_DAG_ID, help="DAG id for single export (default: %(default)s)")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=_repo_root() / "dag_a_manifest.yaml",
        help="Output YAML path for single-DAG mode (default: repo root dag_a_manifest.yaml)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_repo_root() / "dag_manifests",
        help="Directory for --all-dags (default: repo root dag_manifests/)",
    )
    parser.add_argument(
        "--all-dags",
        action="store_true",
        help="Export every DAG from DagBag (include_examples=False) to separate YAML files",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print YAML to stdout instead of writing a file (single-DAG mode only)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Smoke-test operator_call_args for BashOperator + PythonOperator (no YAML write)",
    )
    args = parser.parse_args()

    if args.verify:
        raise SystemExit(verify_operator_call_args(args.dag_id))

    if args.all_dags:
        export_all_dags(args.output_dir)
        return

    manifest = build_manifest(args.dag_id)
    text = _trim_leading_non_yaml(_dump_yaml(manifest))

    if args.stdout:
        print(text, end="")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(str(args.output.resolve()))


if __name__ == "__main__":
    main()
