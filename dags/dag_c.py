from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.sensors.external_task import ExternalTaskSensor
from airflow.sensors.python import PythonSensor
from airflow.utils.task_group import TaskGroup


READY_FILE = "/opt/airflow/data/from_a/ready.txt"


def _ready_file_exists() -> bool:
    return os.path.exists(READY_FILE)


with DAG(
    dag_id="dag_c",
    start_date=datetime(2025, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["demo", "dependency"],
) as dag:
    start = EmptyOperator(task_id="start")

    wait_for_a = ExternalTaskSensor(
        task_id="wait_for_dag_a_complete",
        external_dag_id="dag_a",
        external_task_id="a_complete",
        allowed_states=["success"],
        failed_states=["failed", "skipped", "upstream_failed"],
        execution_delta=None,
        timeout=int(timedelta(hours=6).total_seconds()),
        poke_interval=30,
        mode="reschedule",
    )

    wait_for_b = ExternalTaskSensor(
        task_id="wait_for_dag_b_complete",
        external_dag_id="dag_b",
        external_task_id="b_complete",
        allowed_states=["success"],
        failed_states=["failed", "skipped", "upstream_failed"],
        execution_delta=None,
        timeout=int(timedelta(hours=6).total_seconds()),
        poke_interval=30,
        mode="reschedule",
    )

    wait_for_ready_file = PythonSensor(
        task_id="wait_for_ready_file_from_a",
        python_callable=_ready_file_exists,
        timeout=int(timedelta(hours=6).total_seconds()),
        poke_interval=15,
        mode="reschedule",
    )

    with TaskGroup(group_id="fanout_1") as fanout_1:
        f1 = EmptyOperator(task_id="f1")
        f2 = EmptyOperator(task_id="f2")
        f3 = EmptyOperator(task_id="f3")
        f4 = EmptyOperator(task_id="f4")
        f5 = EmptyOperator(task_id="f5")

        f1 >> [f2, f3, f4]
        [f2, f3] >> f5
        f4 >> f5

    with TaskGroup(group_id="processing") as processing:
        p1 = EmptyOperator(task_id="p1")
        p2 = EmptyOperator(task_id="p2")
        p3 = EmptyOperator(task_id="p3")
        p4 = EmptyOperator(task_id="p4")
        p5 = EmptyOperator(task_id="p5")
        p6 = EmptyOperator(task_id="p6")

        p1 >> [p2, p3]
        [p2, p3] >> p4
        p4 >> [p5, p6]

    with TaskGroup(group_id="publish") as publish:
        pub1 = EmptyOperator(task_id="pub1")
        pub2 = EmptyOperator(task_id="pub2")
        pub3 = EmptyOperator(task_id="pub3")

        [pub1, pub2] >> pub3

    c_complete = EmptyOperator(task_id="c_complete")

    start >> [wait_for_a, wait_for_b, wait_for_ready_file]
    [wait_for_a, wait_for_b, wait_for_ready_file] >> fanout_1 >> processing >> publish >> c_complete
