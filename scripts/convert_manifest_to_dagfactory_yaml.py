"""
Experimental: convert a per-DAG manifest YAML into DagFactory-style YAML + stub Python.

This targets the PyPI ``dag-factory`` library (different from ``dags/dag_factory_loader.py``
in this repo). Use only if you are experimenting with that package; the default demo
loads DAGs from ``dags/dag_factory_config.yml`` via the custom loader.

Requires: PyYAML (``pip install -r scripts/requirements-scripts.txt``).
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import yaml


def parse_callable_name(callable_str: object) -> str:
    match = re.search(r"<callable (.*?)>", str(callable_str))
    if match:
        return match.group(1)
    return "unknown_callable"


def convert(manifest_path: Path, output_yaml_path: Path, output_py_path: Path) -> None:
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    dag_def = manifest.get("dag", {})
    tasks_def = manifest.get("tasks", {})

    df_yaml = {
        dag_def["dag_id"]: {
            "default_args": {
                "owner": "airflow",
                "start_date": dag_def.get("start_date", "2025-01-01T00:00:00+00:00"),
            },
            "schedule_interval": dag_def.get("schedule", "@daily"),
            "catchup": dag_def.get("catchup", False),
            "tags": dag_def.get("tags", []),
            "tasks": {},
        }
    }

    task_id_map: dict[str, str] = {}
    for full_task_id, task_info in tasks_def.items():
        local_task_id = task_info["placement"]["local_task_id"]
        task_id_map[full_task_id] = local_task_id

    python_callables: set[str] = set()

    for full_task_id, task_info in tasks_def.items():
        local_task_id = task_info["placement"]["local_task_id"]
        task_group = task_info["placement"]["task_group"]

        task_dict: dict = {"operator": task_info["operator_class"]}

        if task_group:
            task_dict["task_group_name"] = task_group

        upstreams = task_info.get("upstream_task_ids", [])
        if upstreams:
            task_dict["dependencies"] = [task_id_map[u] for u in upstreams]

        call_args = task_info.get("operator_call_args", {})
        if "bash_command" in call_args:
            task_dict["bash_command"] = call_args["bash_command"]

        if "python_callable" in call_args:
            callable_name = parse_callable_name(call_args["python_callable"])
            python_callables.add(callable_name)
            task_dict["python_callable_name"] = callable_name
            task_dict["python_callable_file"] = (
                f"/opt/airflow/dags/{os.path.basename(output_py_path)}"
            )

        if "op_args" in call_args and call_args["op_args"]:
            task_dict["op_args"] = call_args["op_args"]

        if "op_kwargs" in call_args and call_args["op_kwargs"]:
            task_dict["op_kwargs"] = call_args["op_kwargs"]

        df_yaml[dag_def["dag_id"]]["tasks"][local_task_id] = task_dict

    output_yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with output_yaml_path.open("w", encoding="utf-8") as f:
        yaml.dump(df_yaml, f, sort_keys=False, default_flow_style=False)

    with output_py_path.open("w", encoding="utf-8") as f:
        f.write("import dagfactory\n")
        f.write("from airflow import DAG\n\n")

        for callable_name in python_callables:
            f.write(f"def {callable_name}(*args, **kwargs):\n")
            f.write(f"    # TODO: Implement {callable_name} logic here\n")
            f.write("    pass\n\n")

        f.write(f"config_file = '/opt/airflow/dags/{os.path.basename(output_yaml_path)}'\n")
        f.write("dag_factory = dagfactory.DagFactory(config_file)\n")
        f.write("dag_factory.clean_dags(globals())\n")
        f.write("dag_factory.generate_dags(globals())\n")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--manifest",
        type=Path,
        default=root / "dag_manifests" / "dag_a.yaml",
        help="Path to per-DAG manifest YAML",
    )
    p.add_argument(
        "--out-yaml",
        type=Path,
        default=root / "dag_factory_output" / "dag_a_factory.yaml",
        help="Output DagFactory YAML path",
    )
    p.add_argument(
        "--out-py",
        type=Path,
        default=root / "dag_factory_output" / "dag_a.py",
        help="Output stub Python path for DagFactory",
    )
    args = p.parse_args()
    convert(args.manifest, args.out_yaml, args.out_py)


if __name__ == "__main__":
    main()
