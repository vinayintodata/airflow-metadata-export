"""
Python callables for dag_c — migrated unchanged from the original DAG source.
"""
from __future__ import annotations

import os


READY_FILE = "/opt/airflow/data/from_a/ready.txt"


def _ready_file_exists() -> bool:
    return os.path.exists(READY_FILE)
