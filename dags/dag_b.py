from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.utils.task_group import TaskGroup


with DAG(
    dag_id="dag_b",
    start_date=datetime(2025, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["demo", "dependency"],
) as dag:
    start = EmptyOperator(task_id="start")

    with TaskGroup(group_id="stage_1") as stage_1:
        s1_1 = EmptyOperator(task_id="s1_1")
        s1_2 = EmptyOperator(task_id="s1_2")
        s1_3 = EmptyOperator(task_id="s1_3")
        s1_4 = EmptyOperator(task_id="s1_4")

        s1_1 >> [s1_2, s1_3]
        [s1_2, s1_3] >> s1_4

    with TaskGroup(group_id="stage_2") as stage_2:
        s2_1 = EmptyOperator(task_id="s2_1")
        s2_2 = EmptyOperator(task_id="s2_2")
        s2_3 = EmptyOperator(task_id="s2_3")
        s2_4 = EmptyOperator(task_id="s2_4")
        s2_5 = EmptyOperator(task_id="s2_5")

        s2_1 >> [s2_2, s2_3, s2_4]
        [s2_2, s2_3] >> s2_5
        s2_4 >> s2_5

    with TaskGroup(group_id="stage_3") as stage_3:
        s3_1 = EmptyOperator(task_id="s3_1")
        s3_2 = EmptyOperator(task_id="s3_2")
        s3_3 = EmptyOperator(task_id="s3_3")

        s3_1 >> [s3_2, s3_3]

    b_complete = EmptyOperator(task_id="b_complete")

    start >> stage_1 >> stage_2 >> stage_3 >> b_complete
