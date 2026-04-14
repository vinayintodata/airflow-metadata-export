# Airflow migration demo (Docker Compose)

Local **Apache Airflow 3** stack (Docker Compose) for development and learning—not production.

---

## Contents

1. [What is in this repo](#what-is-in-this-repo)  
2. [Requirements](#requirements)  
3. [Start Airflow](#start-airflow)  
4. [Project layout](#project-layout)  
5. [Shared data folder](#shared-data-folder)  
6. [DAG manifest export](#dag-manifest-export)  
7. [Manifest YAML reference](docs/MANIFEST.md) (file structure and how to read it)  
8. [Configuration notes](#configuration-notes)

---

## What is in this repo

- **`docker-compose.yaml`** — Airflow with CeleryExecutor, PostgreSQL, Redis, workers, scheduler, API server (UI on port **8080**).
- **`dags/`** — DAG definitions.
- **`scripts/dag_a_manifest.py`** — Optional YAML export of DAG structure, tasks, operator arguments, execution order, and cross-DAG edges.
- **`dag_manifests/`** — Example exported YAML (regenerate after you change DAGs).
- **`config/`** — Airflow config mounted into containers.

---

## Requirements

- **Docker Desktop** (Windows) or Docker Engine + Compose plugin  
- **Docker Compose v2**

---

## Start Airflow

From the repository root:

```bash
docker compose up airflow-init
docker compose up -d
```

- First run: `airflow-init` prepares the database.  
- Then start the stack in the background (`-d`) or omit `-d` to see logs in the terminal.

**Airflow UI**

| Item | Value |
|------|--------|
| URL | http://localhost:8080 |
| Default login | `airflow` / `airflow` (unless changed in `.env`) |

Stop the stack:

```bash
docker compose down
```

---

## Project layout

| Path | Purpose |
|------|---------|
| `dags/` | DAG Python files (mounted to `/opt/airflow/dags`). |
| `data/` | Host folder mounted as `/opt/airflow/data` for shared files between tasks or with the host. |
| `logs/` | Airflow logs (created by Docker; listed in `.gitignore`). |
| `config/airflow.cfg` | Custom Airflow configuration. |
| `scripts/dag_a_manifest.py` | Manifest exporter CLI. |
| `dag_manifests/` | Generated YAML exports + `index.yaml`. |
| `docs/MANIFEST.md` | Describes manifest YAML structure and how to read each section. |

---

## Shared data folder

| Location | Path |
|----------|------|
| On your machine (repo) | under `./data/` |
| Inside containers | `/opt/airflow/data` |

`docker-compose.yaml` mounts `./data` into Airflow services. Runtime files under `data/` can be gitignored as needed.

---

## DAG manifest export

For **what each field means** (`global_topological_order`, `execution_order`, `tasks`, `index.yaml`, etc.), see **[docs/MANIFEST.md](docs/MANIFEST.md)**.

Run the script **inside the scheduler container** (the `scripts/` directory is not mounted by default, so pipe the file in).

PowerShell:

```powershell
Get-Content -Raw scripts\dag_a_manifest.py | docker compose exec -T airflow-scheduler python - --all-dags --output-dir /tmp/dag_manifests
docker compose cp airflow-scheduler:/tmp/dag_manifests ./dag_manifests
```

Bash:

```bash
docker compose exec -T airflow-scheduler python - --all-dags --output-dir /tmp/dag_manifests < scripts/dag_a_manifest.py
docker compose cp airflow-scheduler:/tmp/dag_manifests ./dag_manifests
```

**Single DAG** (requires Airflow on the host Python):

```bash
python scripts/dag_a_manifest.py --dag-id <dag_id> -o out.yaml
```

**Smoke test** (operator args):

```powershell
Get-Content -Raw scripts\dag_a_manifest.py | docker compose exec -T airflow-scheduler python - --verify
```

---

## Configuration notes

- **`.env`** — Often used for `AIRFLOW_UID`, `FERNET_KEY`, and secrets. Do not commit secrets. `.env` is gitignored.  
- **`LOAD_EXAMPLES`** — Example DAGs from the Airflow image may appear in the UI; manifests use **`DagBag(include_examples=False)`** so only files under `dags/` are exported.  
- **Resource usage** — This Compose file runs several services; ensure Docker has enough RAM/CPU.

---

## License

The included `docker-compose.yaml` header follows the Apache Airflow project license. Your DAGs and scripts are yours to license as you choose.
