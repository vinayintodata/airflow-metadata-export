# Airflow migration demo (Docker Compose)

Local **Apache Airflow 3** stack with three sample DAGs that model **cross-DAG dependencies**: DAG C waits on tasks in DAG A and DAG B, and on a file written by DAG A.

---

## Contents

1. [What is in this repo](#what-is-in-this-repo)  
2. [Requirements](#requirements)  
3. [Start Airflow](#start-airflow)  
4. [Project layout](#project-layout)  
5. [The three DAGs](#the-three-dags)  
6. [Run the demo](#run-the-demo)  
7. [Shared data folder](#shared-data-folder)  
8. [DAG manifest export](#dag-manifest-export)  
9. [Configuration notes](#configuration-notes)

---

## What is in this repo

- **`docker-compose.yaml`** — Airflow with CeleryExecutor, PostgreSQL, Redis, workers, scheduler, API server (UI on port **8080**).
- **`dags/`** — Your DAG definitions (`dag_a`, `dag_b`, `dag_c`).
- **`scripts/dag_a_manifest.py`** — Optional YAML export of DAG structure, tasks, operator arguments, execution order, and DAG-to-DAG edges (for migration or documentation).
- **`dag_manifests/`** — Example exported YAML (regenerate after you change DAGs).
- **`config/`** — Airflow config mounted into containers.

This setup is for **development and learning**, not production.

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
| `data/` | Host folder mounted as `/opt/airflow/data` (e.g. ready file from DAG A). |
| `logs/` | Airflow logs (created by Docker; listed in `.gitignore`). |
| `config/airflow.cfg` | Custom Airflow configuration. |
| `scripts/dag_a_manifest.py` | Manifest exporter CLI. |
| `dag_manifests/` | Generated YAML exports + `index.yaml`. |

---

## The three DAGs

| DAG ID | Role |
|--------|------|
| **`dag_a`** | Multi-stage graph with TaskGroups (extract / transform / load), branching, and a task that writes **`/opt/airflow/data/from_a/ready.txt`**. |
| **`dag_b`** | Separate pipeline with its own TaskGroups; exposes a final task `b_complete`. |
| **`dag_c`** | Waits on **other DAGs** via `ExternalTaskSensor` (`dag_a.a_complete`, `dag_b.b_complete`) and on a **PythonSensor** that polls until the ready file exists. |

Schedules are **`@daily`** with **`catchup: false`**. New DAGs are created **paused** (`DAGS_ARE_PAUSED_AT_CREATION` in Compose).

---

## Run the demo

1. Open http://localhost:8080 and sign in.  
2. **Unpause** `dag_a` and `dag_b`, then **trigger** them (or wait for the next scheduled run).  
3. Ensure **`dag_a`** has written the ready file (task `write_ready_file`) and both DAGs have succeeded through **`a_complete`** and **`b_complete`**.  
4. **Unpause** and **trigger** `dag_c`.

`dag_c` will block until:

- `dag_a.a_complete` and `dag_b.b_complete` report success for the logical date the sensor expects, and  
- `/opt/airflow/data/from_a/ready.txt` exists (PythonSensor).

If something fails, check **Browse → Task Instances** and container logs: `docker compose logs -f airflow-scheduler`.

---

## Shared data folder

| Location | Path |
|----------|------|
| On your machine (repo) | `data/from_a/ready.txt` |
| Inside containers | `/opt/airflow/data/from_a/ready.txt` |

`docker-compose.yaml` mounts `./data` into Airflow services. The ready file is runtime output; it is **gitignored** so it is not committed.

---

## DAG manifest export

The script parses DAGs with Airflow’s **`DagBag`** (same idea as the scheduler loading `dags/`). It can also merge rows from **`airflow dags list -o json`** when run inside a container.

**What you get**

- **Per-DAG YAML**: execution order (including TaskGroup-local waves), full task metadata, **`operator_call_args`** (e.g. `op_kwargs`, `bash_command`), and outbound cross-DAG references.  
- **`index.yaml`** (with **`--all-dags`**): list of exported DAGs, **aggregated DAG-to-DAG edges**, and a subset of CLI metadata.

**Export all DAGs from `dags/`** (recommended: run inside the scheduler container; `scripts/` is not mounted by default, so pipe the file):

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

**Single DAG** (only if Airflow is installed on the host Python):

```bash
python scripts/dag_a_manifest.py --dag-id dag_a -o dag_a_export.yaml
```

**Smoke test** (Bash + Python operator args) for `dag_a`:

```powershell
Get-Content -Raw scripts\dag_a_manifest.py | docker compose exec -T airflow-scheduler python - --verify
```

---

## Configuration notes

- **`.env`** — Often used for `AIRFLOW_UID`, `FERNET_KEY`, and secrets. Copy from Airflow docs or generate keys; do not commit secrets. `.env` is gitignored.  
- **`LOAD_EXAMPLES`** — Example DAGs from the Airflow image may appear in the UI alongside your `dags/` folder; your manifests use **`DagBag(include_examples=False)`** so only files under `dags/` are exported.  
- **Resource usage** — This Compose file runs several services; ensure Docker has enough RAM/CPU.

---

## License

The included `docker-compose.yaml` header follows the Apache Airflow project license. Your DAGs and scripts are yours to license as you choose.
