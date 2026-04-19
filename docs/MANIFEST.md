# DAG manifest YAML — how to read the files

This guide describes the **YAML files** produced by `scripts/dag_metadata_extract.py` (`--all-dags` or single `--dag-id`). In a **migration** workflow, these files are the **export** artifact; turning them into new DAG code or config is a separate step (another codebase). This guide does not describe Airflow runtime behavior (DagRuns, TaskInstances, logs).

---

## Where the files come from

| Source | What it is |
|--------|------------|
| **DagBag** | DAGs are loaded from Python files under `dags/` (same idea as the scheduler parsing your code). |
| **`airflow dags list -o json`** | Optional rows merged in when the script runs **inside** an Airflow container; adds pause state, `fileloc`, bundle name, etc. |

Nothing in these files is read from task **run** history in the metadata database; it is **definition-time** data from code + CLI snapshot.

---

## File types you will see

| File | Purpose |
|------|---------|
| **`<dag_id>.yaml`** | One manifest **per DAG** (e.g. `dag_a.yaml`). |
| **`index.yaml`** | Produced only with **`--all-dags`**: lists what was exported, **cross-DAG dependency edges**, and a subset of CLI metadata for those DAGs. |

`format_version` is **`1`** for both kinds of file (see `manifest.format_version`).

---

## Per-DAG file (`<dag_id>.yaml`) — top-level keys

Read the file top to bottom; each block has a distinct role.

### `manifest`

| Field | Meaning |
|-------|---------|
| `dag_id` | DAG identifier. |
| `format_version` | Schema version (currently `1`). |
| `kind` | Always `airflow_dag_manifest` for per-DAG files. |
| `warnings` | Parse/import warnings for this DAG’s file, if any; otherwise `null`. |

### `dag`

Short **DAG-level** summary: `dag_id`, `fileloc`, `schedule`, `tags`, `catchup`, `start_date`, `default_args` when present. This is not a full dump of every DAG attribute.

### `global_topological_order`

A **single list of `task_id` strings** in one valid **topological** order (dependencies respected). Use this when you need a **linear reading order** over all tasks.

- Tasks that can run **in parallel** still appear **one after another** in this list; the list does not encode parallelism by itself.

### `global_execution_waves`

A **layering of the whole DAG**:

- Each item has `wave` (integer) and `parallel_tasks` (list of `task_id`).
- Tasks in the **same wave** may run **concurrently** (subject to pools and the executor).
- A **higher** wave number runs **after** all tasks in **lower** waves have finished (for that DAG graph).

Use this when you care about **what can run at the same time** across the entire DAG.

### `execution_order`

Hierarchical view by **TaskGroup** (and root):

- **`segments`**: In global topological order, the DAG is split into **segments** whenever the task’s **registry key** changes (root vs named group; root can appear **twice** if you have root tasks before and after groups).
- Each segment has:
  - `segment_index`, `registry_key`, `task_group_id` (`null` for root),
  - **`local_execution_waves`**: waves **inside that segment only** (dependencies **to tasks outside the segment** are ignored for layering). Same `wave` ⇒ may run in parallel **within that segment**; different waves ⇒ later steps inside the segment.

Use this when you want to **rebuild or reason about TaskGroup blocks** (e.g. “inside `extract`, what runs in parallel?”).

### `tasks`

A **map** keyed by **`task_id`**. Each value is one task’s metadata.

Typical fields (not every task has every field):

| Area | Fields |
|------|--------|
| Identity | `task_id`, `task_type`, `operator_class` |
| Dependencies | `upstream_task_ids`, `downstream_task_ids` |
| Grouping | `placement` (`registry_key`, `task_group`, `local_task_id`, `task_group_path`, …) |
| Operator inputs | **`operator_call_args`** — see below |
| Rest | Serialized operator fields Airflow exposes (`retries`, `pool`, `trigger_rule`, …) |

**`operator_call_args`**

- Built from the operator’s **`template_fields`** (plus `python_callable` when relevant).
- Examples: `op_kwargs`, `op_args`, `bash_command`, `sql`, etc., as **literal or structured values** where the live object allows it.
- **`python_callable`** appears as something like `<callable my_func>` — the real code is not embedded; use the DAG source file for the function body.

**`placement`**

- Tells you which **TaskGroup** (if any) the task belongs to and the **local** task id inside that group.

### `cross_dag_edges_from_this_dag`

List of **outbound** references from this DAG to **other** DAG ids (e.g. `ExternalTaskSensor`, `TriggerDagRunOperator`). Empty list `[]` if there are none.

### `airflow_cli_dag_row`

Present when CLI JSON was parsed successfully: one **row** from `airflow dags list -o json` chosen for this `dag_id` (prefers matching `fileloc`). Fields such as `is_paused`, `owners`, `bundle_name` appear here.

---

## Index file (`index.yaml`)

| Section | Meaning |
|---------|---------|
| `manifest` | `format_version`, `kind: airflow_manifest_index`. |
| `export` | `output_dir`, `dag_ids`, `files` (paths as seen when the export ran). |
| `dag_dependencies_across_dags.edges` | **All** cross-DAG edges collected from every exported DAG (sensor/trigger style relations). |
| `airflow_cli` | `dags_list_json_subset_for_exported_dags`, optional `dags_list_json_error`, and `commands` used. |
| `dagbag_import_errors` | DagBag import errors from the export run, if any. |

Use **`index.yaml`** for a **project-wide** graph of “which DAG waits on or triggers which other DAG.” Use **per-DAG files** for structure and task details inside one DAG.

---

## How to choose which section to use

| Question | Where to look |
|----------|----------------|
| What is the DAG schedule and file path? | `dag` |
| What order can tasks run in, as a single list? | `global_topological_order` |
| What can run in parallel in the **whole** DAG? | `global_execution_waves` |
| What is the structure **per TaskGroup** (waves inside each group)? | `execution_order.segments` |
| Full settings for one task? | `tasks.<task_id>` |
| Operator arguments (kwargs, bash, etc.)? | `tasks.<task_id>.operator_call_args` |
| Does this DAG depend on another DAG? | `cross_dag_edges_from_this_dag`, or **`index.yaml`** for all DAGs at once |
| Pause state / owners from CLI? | `airflow_cli_dag_row` or **`index.yaml`** → `airflow_cli` |

---

## Limitations (by design)

- **Not runtime**: No XCom values, rendered templates, or task instance states.
- **Callables**: Function objects are not serialized as source code.
- **Templated strings**: Stored as in the DAG definition (e.g. Jinja), not rendered per run.
- **CLI**: If `airflow dags list` fails or JSON cannot be parsed, CLI sections may be empty and an error string may appear on the index.

---

## Regenerating manifests

After you change DAG code, re-run the exporter (see the main **README**). Committed files under `dag_manifests/` are **snapshots**; they go stale until you regenerate.
