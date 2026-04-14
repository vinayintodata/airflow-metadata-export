from __future__ import annotations

import os
from datetime import datetime

from airflow import DAG
from airflow.decorators import task
from airflow.operators.empty import EmptyOperator
from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.python import BranchPythonOperator, PythonOperator
from airflow.utils.task_group import TaskGroup
from airflow.utils.trigger_rule import TriggerRule


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


with DAG(
    dag_id="dag_a",
    start_date=datetime(2025, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["demo", "dependency"],
) as dag:
    start = EmptyOperator(task_id="start")

    hello_add = PythonOperator(
        task_id="hello_add",
        python_callable=hello_add,
        op_kwargs={"x": 10, "y": 32},
    )

    branch_on_sum = BranchPythonOperator(
        task_id="branch_on_sum",
        python_callable=pick_branch_after_sum,
    )

    branch_bash_ok = BashOperator(
        task_id="branch_bash_ok",
        bash_command='echo "branch: sum is positive (hello from bash)"',
    )

    branch_bash_else = BashOperator(
        task_id="branch_bash_else",
        bash_command='echo "branch: sum is zero or negative (hello from bash)"',
    )

    after_branch = EmptyOperator(
        task_id="after_branch_join",
        trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    )

    with TaskGroup(group_id="extract") as extract:
        e1 = EmptyOperator(task_id="extract_1")
        e2 = EmptyOperator(task_id="extract_2")
        e3 = EmptyOperator(task_id="extract_3")
        e4 = EmptyOperator(task_id="extract_4")

        e1 >> [e2, e3]
        [e2, e3] >> e4

    with TaskGroup(group_id="transform") as transform:
        t1 = EmptyOperator(task_id="transform_1")
        t2 = EmptyOperator(task_id="transform_2")
        t3 = EmptyOperator(task_id="transform_3")
        t4 = EmptyOperator(task_id="transform_4")
        t5 = EmptyOperator(task_id="transform_5")

        t1 >> [t2, t3]
        [t2, t3] >> t4 >> t5

    with TaskGroup(group_id="load") as load:
        l1 = EmptyOperator(task_id="load_1")
        l2 = EmptyOperator(task_id="load_2")
        l3 = EmptyOperator(task_id="load_3")

        [l1, l2] >> l3

    @task(task_id="write_ready_file")
    def write_ready_file(path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"ready at {datetime.utcnow().isoformat()}Z\n")
        return path

    a_complete = EmptyOperator(task_id="a_complete")

    start >> hello_add >> branch_on_sum >> [branch_bash_ok, branch_bash_else] >> after_branch
    after_branch >> extract >> transform >> load >> write_ready_file(READY_FILE) >> a_complete
