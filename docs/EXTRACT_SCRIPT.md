# Running the DAG Metadata Extractor

The `dag_metadata_extract.py` script is designed to be highly portable. It does not need to be permanently installed or committed to your Airflow environment's repository. You can execute it on the fly across different hosting environments.

**Start with the repository [README](../README.md)** for the full quick start, layout, and how manifests fit into the demo.

This guide explains how to run the extractor on various systems. For **this repo’s Docker Compose** stack, prefer **`docker compose exec -T airflow-scheduler`** (see section 1 below) and copy results with **`docker compose cp`**.

---

## 1. Docker (Local or Remote)

If your Airflow is running in Docker, you don't need to copy the file into the container. You can pipe the script directly into the running Airflow Scheduler container.

### Extract ALL DAGs
**PowerShell (Windows):**
```powershell
# 1. Run the script inside the container and save to /tmp/manifests
Get-Content scripts\dag_metadata_extract.py | docker exec -i <your_scheduler_container_name> python - --all-dags --output-dir /tmp/manifests

# 2. Copy the generated manifests back to your Windows machine
docker cp <your_scheduler_container_name>:/tmp/manifests .\dag_manifests
```

**Bash (Linux / macOS):**
```bash
# 1. Run the script inside the container
docker exec -i <your_scheduler_container_name> python - --all-dags --output-dir /tmp/manifests < scripts/dag_metadata_extract.py

# 2. Copy the generated manifests back
docker cp <your_scheduler_container_name>:/tmp/manifests ./dag_manifests
```

*(Note: If you use Docker Compose, replace `docker exec -i <name>` with `docker compose exec -T airflow-scheduler` and `docker cp` with `docker compose cp`)*

### Extract a SINGLE DAG
```bash
# Bash
docker exec -i <your_scheduler_container_name> python - --dag-id my_specific_dag --stdout < scripts/dag_metadata_extract.py > my_dag.yaml
```

---

## 2. Direct Linux Server / VM (via SSH)

If your Airflow is running directly on a VM (like EC2 or an on-prem server), you should copy the file to the server first.

**1. Copy the file to the server:**
```bash
scp scripts/dag_metadata_extract.py user@your-airflow-server:/tmp/
```

**2. SSH into the server and run it:**
```bash
ssh user@your-airflow-server

# Navigate to where you placed it
cd /tmp

# Extract ALL DAGs
python3 dag_metadata_extract.py --all-dags --output-dir ./manifests

# OR extract a SINGLE DAG
python3 dag_metadata_extract.py --dag-id my_specific_dag -o my_dag.yaml
```

---

## 3. Kubernetes (K8s)

If your Airflow is hosted on Kubernetes (e.g., using the official Helm Chart), you can pipe the script directly into the scheduler pod.

### Extract ALL DAGs
**PowerShell (Windows):**
```powershell
# 1. Execute the script inside the scheduler pod
Get-Content scripts\dag_metadata_extract.py | kubectl exec -i -n <your-namespace> <airflow-scheduler-pod-name> -- python - --all-dags --output-dir /tmp/manifests

# 2. Copy the files back to your local machine
kubectl cp -n <your-namespace> <airflow-scheduler-pod-name>:/tmp/manifests .\dag_manifests
```

**Bash (Linux / macOS):**
```bash
# 1. Execute the script inside the scheduler pod
kubectl exec -i -n <your-namespace> <airflow-scheduler-pod-name> -- python - --all-dags --output-dir /tmp/manifests < scripts/dag_metadata_extract.py

# 2. Copy the files back to your local machine
kubectl cp -n <your-namespace> <airflow-scheduler-pod-name>:/tmp/manifests ./dag_manifests
```

---

## 4. Local Python Environment

If you have Airflow installed locally in a virtual environment, you can run the script directly.

```bash
# Ensure your virtual environment is activated
source venv/bin/activate

# Extract ALL DAGs
python scripts/dag_metadata_extract.py --all-dags --output-dir ./dag_manifests

# Extract a SINGLE DAG
python scripts/dag_metadata_extract.py --dag-id my_specific_dag -o my_dag.yaml
```