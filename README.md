# Airflow metadata export (demo)

This repository is a **demo of the export side** of an **Airflow migration** story: you run Airflow locally, point the extractor at your DAG definitions, and produce **structured YAML manifests** (tasks, dependencies, operator arguments, order). That output is the input you would feed into documentation, diffing, or **another codebase** that **reverse-engineers** new DAGs (e.g. YAML or Python for a target Airflow version or environment).

**Scope here:** export metadata only. **Out of scope for this repo:** generating or rewriting DAG code from manifests—that belongs in a separate project you maintain alongside this one.

If you know basic **Docker**, **Python**, and what a DAG/task are in Airflow, you can follow this README end-to-end.

---

## What this repository is

| Piece | Purpose |
|--------|---------|
| **Docker Compose** | PostgreSQL, Redis, Celery worker, scheduler, API server (web UI), and related services—mirrors a small “real” Airflow deployment. |
| **`dags/dag_factory_loader.py` + `dags/dag_factory_config.yml`** | Defines sample DAGs (`dag_a`, `dag_b`, `dag_c`) from YAML (no hand-written DAG Python files required for the demo). |
| **`scripts/dag_metadata_extract.py`** | **Metadata extractor**: reads the same DAG definitions Airflow uses and writes **manifest YAML** files. |
| **`dag_manifests/`** | **Example output** of the extractor (you can regenerate anytime). Re-export after you change DAGs so paths and task metadata stay accurate. |
| **`docs/MANIFEST.md`** | Field-by-field reference for the manifest files. |

This is **not** a production deployment template.

### How this fits into migration

| Stage | Typical home | Role |
|--------|----------------|------|
| **1. Export** | **This repo** | Run Airflow (or your real environment), run `dag_metadata_extract.py`, get `dag_manifests/*.yaml`. |
| **2. Transform / codegen** | *Your other project* | Read those manifests and reverse-engineer target DAGs (new operators, layout, or Airflow major version). |

The manifests are a **portable snapshot of definition-time metadata**—they are not a substitute for testing DAGs on the destination cluster.

---

## Prerequisites

- **Docker Desktop** (Windows) or Docker Engine with the **Compose V2** plugin  
- About **4 GB RAM** available to Docker (Airflow’s init script warns if lower)

---

## Quick start

### 1. Environment file

Copy the template and set a Fernet key (required by Airflow):

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace `FERNET_KEY` with a key you generate:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep `.env` private; it is **gitignored**.

Optional: set `AIRFLOW_HOST_WEB_PORT` (default **8085**) so this stack’s UI does not clash with **another Airflow already using port 8080** on your machine.

### 2. Start Airflow

From the **repository root**:

```bash
docker compose up airflow-init
docker compose up -d
```

- `airflow-init` runs once to migrate the database and create the default admin user.  
- `docker compose up -d` starts the long-running services in the background.

### 3. Open the web UI

| | |
|--|--|
| **URL** | `http://localhost:8085` (or the port in `AIRFLOW_HOST_WEB_PORT`) |
| **Default login** | `airflow` / `airflow` (unless you changed `_AIRFLOW_WWW_USER_*` in Compose) |

You should see the demo DAGs plus any **example DAGs** shipped with the Airflow image (examples can be turned off in `config/airflow.cfg` / env if desired).

### 4. Stop the stack

```bash
docker compose down
```

---

## Exporting DAG metadata (main workflow)

The extractor must run in an environment where **Airflow and your `dags/` folder** are available—typically the **scheduler container**.

Because `scripts/` is not mounted into the container, **pipe** the script on stdin.

**PowerShell (Windows):**

```powershell
Get-Content -Raw scripts\dag_metadata_extract.py | docker compose exec -T airflow-scheduler python - --all-dags --output-dir /tmp/dag_manifests
docker compose cp airflow-scheduler:/tmp/dag_manifests ./dag_manifests
```

**Bash:**

```bash
docker compose exec -T airflow-scheduler python - --all-dags --output-dir /tmp/dag_manifests < scripts/dag_metadata_extract.py
docker compose cp airflow-scheduler:/tmp/dag_manifests ./dag_manifests
```

**Single DAG** (stdout):

```bash
docker compose exec -T airflow-scheduler python - --dag-id dag_a --stdout < scripts/dag_metadata_extract.py > dag_manifests/dag_a.yaml
```

### What gets written

| Output | Description |
|--------|-------------|
| `dag_manifests/<dag_id>.yaml` | One file per DAG: tasks, dependencies, operator args, topological order, etc. |
| `dag_manifests/index.yaml` | Only with `--all-dags`: list of exported DAGs and **cross-DAG** edges. |

For **every field name and section**, read **[docs/MANIFEST.md](docs/MANIFEST.md)**.

Other run targets (plain Docker, SSH, Kubernetes) are covered in **[docs/EXTRACT_SCRIPT.md](docs/EXTRACT_SCRIPT.md)**.

---

## Repository layout

```
.
├── README.md                 # This file
├── .env.example            # Template for Docker/Airflow env vars (copy to .env)
├── docker-compose.yaml       # Airflow 3 stack (CeleryExecutor, Postgres, Redis, …)
├── config/
│   └── airflow.cfg           # Mounted into containers
├── dags/
│   ├── dag_factory_loader.py # Loads *.yml DAG definitions from this tree
│   ├── dag_factory_config.yml# Demo DAGs (dag_a, dag_b, dag_c)
│   └── include/              # Python callables referenced from YAML
├── plugins/                  # Airflow plugins (empty placeholder)
├── data/                     # Mounted at /opt/airflow/data (shared files / demos)
├── scripts/
│   ├── dag_metadata_extract.py           # Metadata exporter (run inside Airflow)
│   ├── convert_manifest_to_dagfactory_yaml.py  # Optional / experimental (see below)
│   └── requirements-scripts.txt          # PyYAML for optional local-only scripts
├── dag_manifests/            # Example / regenerated manifest YAML + index.yaml
└── docs/
    ├── MANIFEST.md           # Manifest schema and field reference
    └── EXTRACT_SCRIPT.md     # How to run the extractor in Docker, SSH, K8s, etc.
```

Runtime folders **`logs/`** (task logs) and **`.env`** are gitignored. **`dag_factory_output/`** is gitignored (optional converter output).

---

## Optional: experimental DagFactory converter

The PyPI **`dag-factory`** library is **not** used by the default Compose setup. This repo loads YAML via **`dags/dag_factory_loader.py`**.

For experiments only, `scripts/convert_manifest_to_dagfactory_yaml.py` can turn a per-DAG manifest into DagFactory-style YAML + stub Python. Install dependencies locally:

```bash
pip install -r scripts/requirements-scripts.txt
python scripts/convert_manifest_to_dagfactory_yaml.py --help
```

Output defaults to `dag_factory_output/` (ignored by git).

---

## Troubleshooting

| Issue | What to try |
|--------|-------------|
| **Port already in use** | Set `AIRFLOW_HOST_WEB_PORT` in `.env` (e.g. `8085`) and recreate: `docker compose up -d --force-recreate airflow-apiserver` |
| **Empty or stale `dag_manifests/`** | Re-run the **Exporting** commands after changing DAGs |
| **Permission / ownership warnings on Linux** | Set `AIRFLOW_UID` in `.env` to your user id (`id -u`) per [Airflow Docker docs](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html) |

---

## Cursor Agent skill

A **Cursor Agent skill** for this repo lives at **`.cursor/skills/airflow-metadata-demo/SKILL.md`**. It summarizes Compose commands, manifest export, and doc locations so assistants stay consistent with this project.

---

## License

The `docker-compose.yaml` header follows the Apache License 2.0 (Airflow upstream). Your DAGs, scripts, and manifests are yours to license separately.
