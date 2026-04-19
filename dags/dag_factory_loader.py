"""
dag_factory_loader.py
=====================
Generic YAML-to-DAG loader for Apache Airflow (2.x and 3.x).

Scans for **all** ``*.yml`` / ``*.yaml`` files under the dags directory
(recursively) and builds DAG objects from them.  Every YAML key that is
not a loader-reserved keyword is forwarded directly to the operator
constructor, so **any** operator works without code changes here.

Reserved YAML keys per task:
    operator, dependencies, task_group_name

Reserved YAML keys per DAG:
    default_args, schedule, catchup, tags, description,
    doc_md, task_groups, tasks
"""
from __future__ import annotations

import importlib
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from airflow import DAG

try:
    from airflow.sdk import TaskGroup
except ImportError:
    from airflow.utils.task_group import TaskGroup

try:
    from airflow.task.trigger_rule import TriggerRule
except ImportError:
    from airflow.utils.trigger_rule import TriggerRule

log = logging.getLogger(__name__)

DAGS_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

TASK_RESERVED_KEYS = {"operator", "dependencies", "task_group_name"}

DAG_RESERVED_KEYS = {
    "default_args", "schedule", "catchup", "tags", "description",
    "doc_md", "task_groups", "tasks",
}

_TIMEDELTA_RE = re.compile(
    r"^(?:(?P<d>\d+)d)?\s*(?:(?P<h>\d+)h)?\s*(?:(?P<m>\d+)m)?\s*(?:(?P<s>\d+)s)?$"
)


def _import_object(dotted_path: str) -> Any:
    """Import any Python object (class, function, constant) from a dotted path."""
    module_path, _, attr_name = dotted_path.rpartition(".")
    mod = importlib.import_module(module_path)
    return getattr(mod, attr_name)


def _parse_date(val: Any) -> datetime:
    """Flexible date parser: accepts datetime, date, and common string formats."""
    if isinstance(val, datetime):
        return val
    if hasattr(val, "year") and hasattr(val, "month"):
        return datetime(val.year, val.month, val.day)
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                     "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    raise ValueError(f"Cannot parse date: {val!r}")


def _parse_timedelta(val: Any) -> timedelta:
    """Parse a timedelta from seconds (int/float) or human string like '2h30m'."""
    if isinstance(val, timedelta):
        return val
    if isinstance(val, (int, float)):
        return timedelta(seconds=val)
    if isinstance(val, str):
        m = _TIMEDELTA_RE.match(val.strip())
        if m:
            parts = {k: int(v) for k, v in m.groupdict(default="0").items()}
            return timedelta(days=parts["d"], hours=parts["h"],
                             minutes=parts["m"], seconds=parts["s"])
    raise ValueError(f"Cannot parse timedelta: {val!r}")


_TIMEDELTA_KEYS = {
    "retry_delay", "execution_timeout", "sla", "timeout",
    "dagrun_timeout", "max_active_tis_per_dagrun",
}

_DATE_KEYS = {"start_date", "end_date"}

_CALLABLE_KEYS = {
    "python_callable", "on_failure_callback", "on_success_callback",
    "on_retry_callback", "on_execute_callback", "sla_miss_callback",
    "execution_date_fn",
}


def _coerce_value(key: str, val: Any) -> Any:
    """Auto-convert known keys to their expected Python types."""
    if key in _DATE_KEYS and not isinstance(val, datetime):
        return _parse_date(val)
    if key in _TIMEDELTA_KEYS and not isinstance(val, timedelta):
        return _parse_timedelta(val)
    if key in _CALLABLE_KEYS and isinstance(val, str):
        return _import_object(val)
    if key == "trigger_rule" and isinstance(val, str):
        return TriggerRule(val)
    return val


def _build_default_args(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: _coerce_value(k, v) for k, v in raw.items()}


def _build_dag(dag_id: str, dag_config: dict[str, Any]) -> DAG:
    """Build one DAG from a YAML config dict — fully generic."""
    default_args = _build_default_args(dag_config.get("default_args", {}))

    dag_kwargs: dict[str, Any] = {
        "dag_id": dag_id,
        "default_args": default_args,
        "schedule": dag_config.get("schedule"),
        "catchup": dag_config.get("catchup", False),
        "tags": dag_config.get("tags", []),
    }
    if "description" in dag_config:
        dag_kwargs["description"] = dag_config["description"]
    if "doc_md" in dag_config:
        dag_kwargs["doc_md"] = dag_config["doc_md"]
    for extra_key in set(dag_config) - DAG_RESERVED_KEYS:
        dag_kwargs[extra_key] = _coerce_value(extra_key, dag_config[extra_key])

    dag = DAG(**dag_kwargs)

    task_groups_config = dag_config.get("task_groups", {})
    task_groups: dict[str, TaskGroup] = {}
    with dag:
        for tg_name, tg_conf in task_groups_config.items():
            tg_conf = tg_conf or {}
            task_groups[tg_name] = TaskGroup(
                group_id=tg_name,
                tooltip=tg_conf.get("tooltip", ""),
            )

    tasks_config = dag_config.get("tasks", {})
    if isinstance(tasks_config, list):
        tasks_config = {t["task_id"]: t for t in tasks_config}

    task_objects: dict[str, Any] = {}

    with dag:
        for task_key, task_conf in tasks_config.items():
            operator_path = task_conf["operator"]
            operator_cls = _import_object(operator_path)

            tg_name = task_conf.get("task_group_name")
            tg = task_groups.get(tg_name) if tg_name else None

            kwargs: dict[str, Any] = {"task_id": task_key}
            if tg:
                kwargs["task_group"] = tg

            for k, v in task_conf.items():
                if k in TASK_RESERVED_KEYS or k == "task_id":
                    continue
                kwargs[k] = _coerce_value(k, v)

            task_obj = operator_cls(**kwargs)
            task_objects[task_key] = task_obj

        for task_key, task_conf in tasks_config.items():
            deps = task_conf.get("dependencies", [])
            for dep_key in deps:
                if dep_key in task_objects:
                    task_objects[dep_key] >> task_objects[task_key]

    return dag


def load_yaml_dags(config_path: Path, globals_dict: dict) -> None:
    """Load all DAGs from a single YAML config file."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if not config:
        return
    for dag_id, dag_config in config.items():
        if dag_id == "default":
            continue
        if not isinstance(dag_config, dict):
            continue
        try:
            dag = _build_dag(dag_id, dag_config)
            globals_dict[dag_id] = dag
        except Exception:
            log.exception("Failed to build DAG '%s' from %s", dag_id, config_path)


def discover_and_load(dags_dir: Path, globals_dict: dict) -> None:
    """Recursively find all YAML files under dags_dir and load DAGs from them."""
    for pattern in ("**/*.yml", "**/*.yaml"):
        for yml_path in sorted(dags_dir.glob(pattern)):
            load_yaml_dags(yml_path, globals_dict)


discover_and_load(DAGS_DIR, globals())
