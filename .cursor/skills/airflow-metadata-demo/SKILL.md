---
name: airflow-metadata-demo
description: >-
  Works with the airflow_migration demo: Airflow 3 Docker Compose stack and
  scripts/dag_metadata_extract.py exporting DAG manifest YAML under dag_manifests/
  for migration planning. This repo covers export only; reverse-engineering DAGs from
  manifests lives in a separate codebase. Use when editing DAGs, manifests, compose,
  or explaining how export fits into Airflow migration.
---

# Airflow metadata demo (this repository)

## Project purpose

Local **Apache Airflow 3** (Docker Compose) plus a **metadata extractor** that writes
YAML under `dag_manifests/` (definition-time metadata). This repo demonstrates **export**
for migration workflows; **consumers** that rebuild DAGs from manifests are **out of scope**
here and belong in another project.

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
