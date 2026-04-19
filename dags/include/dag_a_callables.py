"""
Python callables for dag_a — migrated unchanged from the original DAG source.
"""
from __future__ import annotations

import os
from datetime import datetime


DATA_DIR = "/opt/airflow/data"
READY_FILE = os.path.join(DATA_DIR, "from_a", "ready.txt")


def hello_add(x: int, y: int) -> int:
    """Hello world: add two integers and log the result."""
    result = x + y
    print(f"hello world: {x} + {y} = {result}")
    return result


def pick_branch_after_sum(**context) -> str:
    """Branch: if sum is positive, run bash_ok; else bash_else."""
    ti = context["ti"]
    total = ti.xcom_pull(task_ids="hello_add")
    if total is None:
        return "branch_bash_else"
    if total > 0:
        return "branch_bash_ok"
    return "branch_bash_else"


def write_ready_file(path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"ready at {datetime.utcnow().isoformat()}Z\n")
    return path
