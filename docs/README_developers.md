
## NMDC Workflow Scheduler

This module implements a job scheduling system for the NMDC workflow automation framework. It identifies candidate workflow jobs from upstream process nodes and generates executable job records for compatible and enabled workflows.

### Overview

The core component is the `Scheduler` class, which:

- Loads and parses workflow configurations from a YAML file
- Periodically queries the database for candidate activities (`WorkflowProcessNodes`) that could trigger downstream workflows
- Determines whether a new job should be created (i.e., not already completed or canceled)
- Constructs and stores job definitions in a MongoDB jobs collection
- Supports dry runs, skiplists, allowlists, and forced version scheduling

This system enables robust and automatic chaining of workflows by examining upstream activities and creating jobs that meet version compatibility and data availability requirements.

### Poetry Environment

**To activate the poetry environment of your branch:**

```bash
poetry install
poetry shell
```

The `poetry install` command uses the `poetry.lock` file to create a virtual environment with the correct dependencies, ensuring consistency across development setups. [(Documentation)](https://python-poetry.org/docs/basic-usage/#installing-with-poetrylock)

**To update the lock file after modifying dependencies:**

```bash
poetry update
```

Whenever you update the `pyproject.toml` file—such as when upgrading JAWS or NMDC Schema dependencies—you should also update the `poetry.lock` file. This ensures that all dependency changes are properly recorded. Before merging any branch into `main`, it is best practice to run `poetry update` to refresh the lock file. Failing to do so can cause CI/CD tests to fail due to mismatched environments, especially if schema changes are not reflected in the test fixtures or lock file. [(Documentation)](https://python-poetry.org/docs/basic-usage/#updating-dependencies-to-their-latest-versions)



<details><summary>Poetry update example</summary>

```
>> poetry update
The currently activated Python version 3.13.5 is not supported by the project (>=3.10,<3.12).
Trying to find and use a compatible version. 
Using python3.11 (3.11.13)
The lock file might not be compatible with the current version of Poetry.
Upgrade Poetry to ensure the lock file is read properly or, alternatively, regenerate the lock file with the `poetry lock` command.
Updating dependencies
Resolving dependencies... (5.9s)

Package operations: 0 installs, 6 updates, 1 removal

  • Removing roman-numerals-py (3.1.0)
  • Updating certifi (2025.7.9 -> 2025.7.14)
  • Updating jsonschema (4.24.0 -> 4.25.0)
  • Updating orderly-set (5.4.1 -> 5.5.0)
  • Updating linkml-runtime (1.9.3 -> 1.9.4)
  • Updating slack-sdk (3.35.0 -> 3.36.0)
  • Updating nmdc-schema (11.8.0 -> 11.9.1)

Writing lock file

>> poetry install
The currently activated Python version 3.13.5 is not supported by the project (>=3.10,<3.12).
Trying to find and use a compatible version. 
Using python3.11 (3.11.13)
Installing dependencies from lock file

Package operations: 0 installs, 3 updates, 0 removals

  • Updating isodate (0.6.1 -> 0.7.2)
  • Downgrading rdflib (6.3.2 -> 6.2.0)
  • Downgrading sphinx (8.2.3 -> 8.1.3)

Installing the current project: nmdc-automation (0.1.0)

>> poetry shell
The currently activated Python version 3.13.5 is not supported by the project (>=3.10,<3.12).
Trying to find and use a compatible version. 
Using python3.11 (3.11.13)
Spawning shell within /path/to/Library/Caches/pypoetry/virtualenvs/nmdc-automation-FtOYRXpA-py3.11
. /path/to/Library/Caches/pypoetry/virtualenvs/nmdc-automation-FtOYRXpA-py3.11/bin/activate

(nmdc-automation-py3.11) >> exit
exit

>> ▌
```

</details>

### Workflow Configuration

The Scheduler loads a set of workflow definitions using:

```python
self.workflows = load_workflow_configs(workflow_yaml)
```

#### Process Node Discovery

Candidate trigger activities are identified using:

```python
load_workflow_process_nodes(self.db, self.workflows, allowlist)
```

This function scans the database for completed upstream `PlannedProcess` records (like DataGeneration or WorkflowExecution), and matches them to downstream workflows defined in the YAML configuration.

#### Job Creation Logic

Each matching process node is checked to see if:

- The workflow is enabled
- No previous job already exists for this process node
- No equivalent workflow execution already exists (matching major/minor version)

If these checks pass, the Scheduler prepares a job config including:

- Workflow WDL path, repository, and version
- Input data object URLs
- Execution metadata (e.g., `was_informed_by`, iteration, input prefix)
- Output IDs, optionally pre-minted via `NmdcRuntimeApi`

The resulting job record is inserted into MongoDB.

### Key Classes & Functions

#### Scheduler

Main orchestrator for job scheduling.

| Method              | Description                                                      |
|---------------------|------------------------------------------------------------------|
| `__init__`          | Loads workflows, sets up API, applies force mode                 |
| `cycle()`           | Performs one scheduling pass                                     |
| `run()`             | Async wrapper to run `cycle()` in a loop                         |
| `create_job_rec()`  | Constructs job records from workflow and input data              |
| `find_new_jobs()`   | Finds valid job opportunities for a given `WorkflowProcessNode`  |

#### SchedulerJob

Lightweight container holding a `WorkflowConfig` and its triggering activity.

```python
within_range(wf1, wf2)
```

Checks if two workflows are version-compatible (same major.minor version, or exact if forced).

### Environment Variables

| Name                      | Description                                              |
|---------------------------|----------------------------------------------------------|
| `NMDC_WORKFLOW_YAML_FILE` | Path to the workflow configuration YAML file             |
| `FORCE`                   | If set to `"1"`, disables version skipping logic         |
| `DRYRUN`                  | If set to `"1"`, jobs will not be inserted into MongoDB  |
| `SKIPLISTFILE`            | File with newline-separated activity IDs to skip         |
| `ALLOWLISTFILE`           | File with newline-separated process node IDs to allow    |
| `MOCK_MINT`               | If set, use test ID mints instead of real ones           |

### Example

#### Running Scheduler

To run the Scheduler:

```bash
python sched.py site_configuration.toml workflows.yaml
```

To dry-run the scheduler for testing:

```bash
DRYRUN=1 python sched.py site_configuration.toml workflows.yaml
```

To use specific allowlisted nodes:

```bash
ALLOWLISTFILE=my_allowlist.txt python sched.py site_configuration.toml workflows.yaml
```

### Dependencies

- `nmdc_automation.api.NmdcRuntimeApi`
- `nmdc_automation.workflow_automation.workflow_process.load_workflow_process_nodes`
- MongoDB (for job storage)
- `semver` (for version compatibility checking)

---

## NMDC Workflow Process Node Loader

📚 **load_workflow_process_nodes: Workflow Activity Graph Builder**

This module constructs a directed acyclic graph (DAG) of `WorkflowProcessNode` objects from the database by:

- Loading relevant activities from the database (such as sequencing or processing records)
- Filtering and validating activities according to workflow configuration criteria
- Associating each activity with its corresponding input and output DataObjects
- Resolving parent-child relationships between nodes based on shared data dependencies

The result is a graph of processing activities that reflects the actual execution history and dependencies of workflows in your system.

### Algorithm Overview

**Inputs:**

- MongoDB database handle (`db`)
- List of `WorkflowConfig` objects (`workflows`)
- Optional list of record IDs to restrict analysis (`allowlist`)

**Output:**

- List of fully linked `WorkflowProcessNode` objects

1. **Load Required Data Objects**

    ```python
    get_required_data_objects_map()
    ```

    - Extracts and loads all DataObjects from the database that match input/output types required by the workflows.
    - Builds a dictionary mapping `DataObject.id` → `DataObject`.

2. **Identify Relevant Workflow Activities**

    ```python
    get_current_workflow_process_nodes()
    ```

    - Divides workflows by type:
        - Data Generation (e.g., sequencing) records from `data_generation_set`
        - Workflow Execution records from `workflow_execution_set`
    - Queries the DB for records that match:
        - The workflow’s `analyte_category`
        - Input/output requirements (`filter_input_objects` and `filter_output_objects`)
        - Version compatibility (based on major version match)
        - `was_informed_by` links to relevant DataGeneration records
    - Wraps each matched DB record as a `WorkflowProcessNode`

3. **Associate Nodes with Their Output Data Objects**

    ```python
    _map_nodes_to_data_objects()
    ```

    - Maps each node’s output DataObjects back to the node that produced them.
    - Detects and warns about duplicate data object IDs (possible data hygiene issue).

4. **Resolve Parent-Child Relationships**

    ```python
    _resolve_relationships()
    ```

    - For each node, checks its inputs.
    - If another node produced one of its inputs and matches an expected parent workflow, link it as the parent.
    - Adds parent and children pointers to represent execution order.

**Result**

You get a fully connected activity graph rooted in your database's provenance data.

Each node knows:

- Its workflow
- The data it consumed and produced
- Its immediate parent and children nodes (if applicable)

**Developer Notes**

- The `_within_range()` version check assumes compatibility if major versions match.
- The system warns about missing data or mismatches in `was_informed_by` lineage.
- This logic assumes workflows have exactly one analyte category.

### Diagrams

For more information about connections to the Schema, refer to [this documentation](https://microbiomedata.github.io/nmdc-schema/typecode-to-class-map/). 

![Scheduler and Related Classes](Workflow-Automation-Scheduler-Classes.png)

![Workflow Process Node and Related Classes](Workflow-Automation-WorkflowProcessNode_and_Related_Classes.png)

![Workflow Process Node Graph](Workflow-Automation-WorkflowProcessNode.png)

![Watcher and Related Classes](Workflow-Automation-Refactored-Watcher.png)

![Workflow Automation System Interactions](Workflow-Automation-Interactions.png)

