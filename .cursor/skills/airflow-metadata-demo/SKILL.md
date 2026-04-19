---
name: airflow-metadata-demo
description: >-
  Works with the airflow_migration demo repository: Airflow 3 Docker Compose stack,
  DAG manifest YAML export via scripts/dag_metadata_extract.py, and optional
  DagFactory-style conversion. Use when the user edits DAGs, manifests, docker-compose,
  or asks how to export metadata, run the stack, or interpret dag_manifests output.
---

# Airflow metadata demo (this repository)

## Project purpose

Local **Apache Airflow 3** (Docker Compose) plus a **metadata extractor** that writes
YAML under `dag_manifests/` describing DAG definitions (tasks, dependencies, operators) for documentation or migration tooling.

## Stack commands

Run from the **repository root**:

- First-time DB: `docker compose up airflow-init`
- Start: `docker compose up -d`
- Stop: `docker compose down`

UI (default host port **8085**): `http://localhost:${AIRFLOW_HOST_WEB_PORT:-8085}`  
Login defaults: `airflow` / `airflow` unless overridden in `.env`.

Copy `.env.example` to `.env` and set `FERNET_KEY` before running.

## Export manifests (inside scheduler container)

`scripts/` is **not** mounted into the image; **pipe** the script into `airflow-scheduler`:

**PowerShell:**

```powershell
Get-Content -Raw scripts/dag_metadata_extract.py | docker compose exec -T airflow-scheduler python - --all-dags --output-dir /tmp/dag_manifests
docker compose cp airflow-scheduler:/tmp/dag_manifests ./dag_manifests
```

**Bash:**

```bash
docker compose exec -T airflow-scheduler python - --all-dags --output-dir /tmp/dag_manifests < scripts/dag_metadata_extract.py
docker compose cp airflow-scheduler:/tmp/dag_manifests ./dag_manifests
```

## Where to read documentation

| Topic | File |
|-------|------|
| Repo overview, layout, quick start | `README.md` |
| Manifest YAML field reference | `docs/MANIFEST.md` |
| Docker / SSH / K8s variants | `docs/EXTRACT_SCRIPT.md` |

## DAGs in this demo

DAGs are defined in **`dags/dag_factory_config.yml`** and loaded by **`dags/dag_factory_loader.py`** (custom YAML loader, not the PyPI `dag-factory` package).

## Optional local script

`scripts/convert_manifest_to_dagfactory_yaml.py` is **experimental** and targets the PyPI DagFactory library; ignore unless the user explicitly asks for it. Requires `pip install -r scripts/requirements-scripts.txt`.

## Conventions

- Prefer **forward slashes** in docs and script examples (`scripts/foo.py`).
- Do not commit `.env`; use `.env.example` for templates only.
