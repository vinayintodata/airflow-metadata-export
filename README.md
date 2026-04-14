# Airflow (Docker Compose) demo: DAG A + DAG B -> DAG C

This project runs Apache Airflow locally via Docker Compose and includes three DAGs:

- `dag_a`: complex graph (series + parallel) and **writes a “ready” file** to `/opt/airflow/data/from_a/ready.txt`
- `dag_b`: complex graph (series + parallel)
- `dag_c`: starts only after:
  - **DAG-to-DAG dependency**: `dag_a.a_complete` and `dag_b.b_complete` are successful (same logical date)
  - **File watcher**: the ready file from `dag_a` exists

## Prereqs

- Docker Desktop (Windows)
- Docker Compose v2

## Start Airflow

From this folder:

```bash
docker compose up airflow-init
docker compose up
```

Airflow UI:

- URL: `http://localhost:8080`
- user/pass: `airflow` / `airflow`

## Run the DAGs

These DAGs are set to `@daily` and are **paused at creation** in the provided compose file.

In the UI:

- Unpause `dag_a` and `dag_b` and trigger them (or wait for scheduler)
- After both succeed, unpause/trigger `dag_c`

`dag_c` will wait on:

- ExternalTaskSensors for `dag_a.a_complete` and `dag_b.b_complete`
- A PythonSensor that checks `/opt/airflow/data/from_a/ready.txt`

## Where the “watched” file lives

- On host: `./data/from_a/ready.txt`
- In containers: `/opt/airflow/data/from_a/ready.txt`

This works because `docker-compose.yaml` mounts `./data` into all Airflow services.

## DAG manifests (export)

The script `scripts/dag_a_manifest.py` builds YAML manifests from parsed DAGs (and optional `airflow dags list -o json` metadata). Export all DAGs under `dags/` to `dag_manifests/` (plus `index.yaml` for cross-DAG edges):

```bash
Get-Content scripts/dag_a_manifest.py | docker compose exec -T airflow-scheduler python - --all-dags --output-dir /tmp/m
docker compose cp airflow-scheduler:/tmp/m ./dag_manifests
```

Single DAG: `python scripts/dag_a_manifest.py --dag-id dag_a -o out.yaml` (requires Airflow on `PYTHONPATH`, or use the same Docker pipe with `-o` under a mounted path).
