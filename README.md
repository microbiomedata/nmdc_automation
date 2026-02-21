[![CI](https://github.com/microbiomedata/nmdc_automation/actions/workflows/blt.yml/badge.svg)](https://github.com/microbiomedata/nmdc_automation/actions/workflows/blt.yml)
![Tests](./badges/tests.svg)
![Coverage](./badges/coverage.svg)

<!-- Pytest Coverage Comment:Begin -->
<!-- Pytest Coverage Comment:End -->

# nmdc_automation

An automation framework for running sequential metagenome analysis jobs and making the outputs available as metadata in the NMDC database and data objects on the NMDC data portal.

> **New to this project?** Start with the [Onboarding & Access Setup](docs/README_troubleshooting.md#onboarding--access-setup) section of the troubleshooting guide to get your NERSC, SPIN, and MongoDB access in place, then return here.

## Table of Contents

- [nmdc\_automation](#nmdc_automation)
  - [Table of Contents](#table-of-contents)
  - [Installation](#installation)
    - [Requirements](#requirements)
    - [MongoDB (macOS)](#mongodb-macos)
    - [Project Setup](#project-setup)
  - [Overview](#overview)
    - [System Configuration](#system-configuration)
      - [Site Config](#site-config)
      - [Workflow Definitions](#workflow-definitions)
  - [Quick Start](#quick-start)
    - [Running the Scheduler on NERSC Rancher2](#running-the-scheduler-on-nersc-rancher2)
      - [Managing Allow Lists](#managing-allow-lists)
    - [Running the Watcher on NERSC Perlmutter](#running-the-watcher-on-nersc-perlmutter)
  - [Processing a Study](#processing-a-study)
    - [1. Get the Study ID](#1-get-the-study-id)
    - [2. Check Workflow Status](#2-check-workflow-status)
    - [3. Take Action Based on Results](#3-take-action-based-on-results)
  - [Reference: Job \& State Records](#reference-job--state-records)
    - [Job Document Schema](#job-document-schema)
    - [Watcher State File](#watcher-state-file)
    - [MongoDB Queries](#mongodb-queries)
    - [JAWS](#jaws)
  - [Handling Failed Jobs](#handling-failed-jobs)

---

## Installation

### Requirements

- Python 3.11
- Poetry 2.2.1 — [installation instructions](https://python-poetry.org/docs/#installing-with-pipx)
- `mongodb-community` installed and running locally

### MongoDB (macOS)

```bash
brew tap mongodb/brew
brew install mongodb-community
brew services start mongodb-community
```

Full installation instructions for other platforms: [MongoDB docs](https://docs.mongodb.com/manual/tutorial/install-mongodb-on-os-x/)

### Project Setup

```bash
# 1. Clone the repository
git clone https://github.com/microbiomedata/nmdc_automation.git
cd nmdc_automation

# 2. Install dependencies
poetry install

# 3. Activate the environment
eval $(poetry env activate)

# 4. Run tests to verify setup
make test
```

---

## Overview

### System Configuration

#### Site Config

Site-specific configuration is provided by a `.toml` file. It defines:

1. URL and credentials for the NMDC API
2. Staging and data filesystem locations for the site
3. Job runner service URLs
4. Path to the Watcher state file

#### Workflow Definitions

Workflow definitions in a `.yaml` file describe each analysis step, specifying:

1. Name, type, version, WDL, and git repository for each workflow
2. Inputs, outputs, and workflow execution steps
3. Data object types, description, and name templates for processing workflow output data

**Developer details:** For architecture, implementation internals, algorithm details, class references, version-compatibility rules, and testing, see the [Developer Documentation](docs/README_developers.md).

---

## Quick Start

Both the Scheduler and the Watcher are run with `nohup` (No Hangup) to prevent termination when the terminal session ends. This causes `stdout` and `stderr` to be written to `nohup.out` in addition to the per-session `*{dev|prod}.log` and running `*{dev|prod}_full.log` files. The `nohup.out` files are cleared manually by the user at each (re)start; the per-session logs are automatically overwritten each time.

### Running the Scheduler on NERSC Rancher2

The Scheduler is a Dockerized application running on [Rancher](https://rancher2.spin.nersc.gov).

1. In [SPIN Rancher](https://rancher2.spin.nersc.gov), navigate to the correct cluster:
   - Production: **Cluster: `production` → Workloads → Deployments → Namespace: `nmdc` → scheduler**
   - Development / pre-release testing: **Cluster: `production` → Workloads → Deployments → Namespace: `nmdc-dev` → scheduler**
   - Verify the image is running the correct version for production instance, or the desired release candidate for development instance.
   - See [Release Documentation](https://github.com/microbiomedata/infra-admin/blob/main/releases/nmdc-automation.md) for more information.
2. Find the `scheduler` deployment and select **Execute Shell** from the three dot dropdown.
3. `cd /conf` — all following actions take place in this directory.
4. Update `allow.lst` with the Data Generation IDs to schedule:
   1. Copy the list of Data Generation IDs to your clipboard.
   2. \* `cat > allow.lst` to overwrite existing allow list, or `cat >> allow.lst` to append.
      - \*See [Managing Allow Lists](#managing-allow-lists)
   3. Paste your IDs (`Command+V`).
   4. Press `Return` to ensure a blank line at the end.
   5. Press `Control+D` to terminate the `cat` command.
5. `./run_scheduler.sh status` to check if anything is currently running.
   - `./run_scheduler.sh stop` to manually terminate the process without restarting.
6. Start or restart the Scheduler:
   1. `rm nohup.out` to clear the nohup log (optional but recommended).
   2. `nohup ./run_scheduler.sh &`
      - Run without `nohup` only for troubleshooting or development.
      - `./run_scheduler.sh -h` to see all running options.
      - `[-d/--debug]` for more verbose logging.
7. `cat sched-{dev|prod}.log` or `tail sched-{dev|prod}.log` to monitor Scheduler activity.
   - By default, calling `./run_scheduler.sh` deletes `sched-{dev|prod}.log` and restarts the Scheduler.
  
<details><summary>Startup script options</summary>

```
Usage: ./run_scheduler.sh [COMMAND] [--allowlist PATH] [--yaml PATH] [--toml PATH] [OPTIONS]

Commands:
  stop                   Stop the running scheduler
  status                 Show scheduler status
  By default, if no command is called, scheduler will start

Options:
  -a, --allowlist PATH   Path to allowlist file     (default: /conf/allow.lst)
  -w, --workflows PATH   Path to workflow YAML file (default: )
  -c, --config PATH      Path to site config CONF   (default: /conf/site_configuration.toml)
  -p, --port PORT        MongoDB port number        (default: 27017)
  -s, --skiplist PATH    Path to skiplist file      (default: )
  -i, --pidfile PATH     Path to PID file           (default: /conf/sched-prod.pid)
  -l, --logfile PATH     Path to log file           (default: /conf/sched-prod.log)
  -L, --logfull PATH     Path to full log file      (default: /conf/sched-prod_full.log)
  -d, --debug            Enable debug mode          (increases logging)
  -k, --mock             Use fake IDs for testing   (no real API minting)
  -n, --dryrun           Jobs not inserted into MongoDB
  -f, --force            Ignore version compatibility checks
  -m, --mute             Silence Slack notifs
  -t, --test             Run wrapper in test mode
  -ta, --actual          Run wrapper in test mode with sched code
  -h, --help             Show this help message
```
</details>


#### Managing Allow Lists

The `/conf/submit_to_scheduler/` directory on the prod Scheduler contains saved allow lists for tracking multiple studies. Use the naming convention:

`t[###]_[general_study_name]_[one_word_note]_YYYYMMDD.lst`

Example: `t1372_mendota_mags_20260212.lst`

**Workflow:**
1. Save your Data Generation IDs to a file in `/conf/submit_to_scheduler/`
2. When ready to schedule, concatenate files and overwrite `/conf/allow.lst`:
    ```bash
    cat [list1] [list2] > /conf/allow.lst
    ```
3. Restart the Scheduler

**Important notes:**
- An empty allow list will not start the Scheduler. 
- The allow list is only read once at Scheduler startup.
- The Scheduler will only check the last submitted list of IDs. If the allow list file changes without being resubmitted to the Scheduler, the changes will not be seen.
- If downstream workflows stop scheduling despite no errors, the Scheduler may need the upstream IDs re-submitted (it checks for downstream processes only after reading an ID from the allow list).
- Do not rely on the file contents to track active IDs — keep your own records in `/conf/submit_to_scheduler/`.
  
---

### Running the Watcher on NERSC Perlmutter

The Watcher is a Python application running on a login node on Perlmutter. All instructions below assume you are logged in as `nmdcda@perlmutter.nersc.gov`. For initial access setup, see [Onboarding & Access Setup](docs/README_troubleshooting.md#onboarding--access-setup).

Watcher code and config files are in `/global/homes/n/nmdcda/nmdc_automation/{dev|prod}`.

1. Navigate to the login node where the Watcher was last run:
   ```bash
   cat ~/nmdc_automation/{dev|prod}/host-{dev|prod}.last
   ssh login[node #]
   ```

2. Ensure you have the desired version of `nmdc_automation`:
   ```bash
   cd ~/nmdc_automation/{dev|prod}/nmdc_automation
   git status                        # check current tag
   git fetch --all --prune
   git checkout tags/[release-version]
   ```

3. Set up the environment:
   ```bash
   eval "$__conda_setup"             # load conda
   poetry install                    # install the project
   eval $(poetry env activate)       # activate the environment
   ```

   The prompt will display `(nmdc-automation-py3.11)` when the environment is active.

    <details><summary>Full setup example</summary>

    ```bash
    (nersc-python) nmdcda@login37:~> cat /global/homes/n/nmdcda/nmdc_automation/prod/host-prod.last
    login17
    (nersc-python) nmdcda@login37:~> ssh login17
    (nersc-python) nmdcda@perlmutter:login17:~> eval "$__conda_setup"
    (base) nmdcda@perlmutter:login17:~> cd ~/nmdc_automation/prod/nmdc_automation/
    (base) nmdcda@perlmutter:login17:~/nmdc_automation/prod/nmdc_automation> poetry install
    Installing dependencies from lock file

    No dependencies to install or update

    Installing the current project: nmdc-automation (0.0.0)
    (base) nmdcda@perlmutter:login17:~/nmdc_automation/prod/nmdc_automation> eval $(poetry env activate)
    (nmdc-automation-py3.11) (base) nmdcda@perlmutter:login17:~/nmdc_automation/prod/nmdc_automation>
    ```
    </details>

    <details><summary>Shortcut: auto-{dev|prod} function</summary>

    A function in `~/.bashrc` of the `nmdcda` account combines steps 2–3. Once you are on the correct login node, call `auto-{dev|prod}` to run them automatically:

    ```bash
    auto-{dev|prod}() {
        eval "$__conda_setup"
        cd /global/homes/n/nmdcda/nmdc_automation/{dev|prod}/nmdc_automation
        poetry install
        eval $(poetry env activate)
        cd /global/homes/n/nmdcda/nmdc_automation/{dev|prod}/
    }
    ```

    There is also an alias for activating the poetry environment on its own:

    ```bash
    alias poetry-shell='eval $(poetry env activate)'
    ```
    </details>

4. Change to the working directory:
   - `/global/homes/n/nmdcda/nmdc_automation/prod`
   - `/global/homes/n/nmdcda/nmdc_automation/dev`

5. Check for an existing Watcher process:
   ```bash
   ./run_watcher_{dev|prod}.sh status
   ```

    <details><summary>Example status output</summary>

    ```bash
    (nmdc-automation-py3.11) (base) nmdcda@perlmutter:login17:~/nmdc_automation/prod> ./run_watcher_prod.sh status
    Watcher is running (PID 1429358)
        PID USER         ELAPSED COMMAND
    1429309 nmdcda      05:23:01 /bin/bash ./run_watcher_prod.sh
    1429340 nmdcda      05:23:00 tail -n 0 -F watcher-prod.log
    1429341 nmdcda      05:23:00 /bin/bash ./run_watcher_prod.sh
    1429358 nmdcda      05:23:00 python -u -m nmdc_automation.run_process.run_workflows watcher --config /global/homes/n/nmdcda/nmdc_automation/prod/site_configuration_nersc_prod.toml daemon
    1429359 nmdcda      05:23:00 /bin/bash ./run_watcher_prod.sh
    1429360 nmdcda      05:23:00 tee -a watcher-prod.log watcher-prod_full.log

    Checking JAWS jobs going back 1 day...
    1     "status_detail": "At least one task has requested resources but no tasks have started running yet",
    1     "status": "queued",
    42    "status_detail": "The run is complete.",
    42    "status": "done",
    ```
    </details>

6. To stop the Watcher without restarting (you must be on the correct login node):
   ```bash
   ./run_watcher_{dev|prod}.sh stop
   ```
   This terminates all associated processes. Note: the `run_watcher_{dev|prod}.sh` script handles stopping and restarting automatically; manual `kill -9` is no longer necessary.

7. Start or restart the Watcher:
   ```bash
   rm nohup.out                              # optional but recommended
   nohup ./run_watcher_{dev|prod}.sh &
   ```
   - Run without `nohup` only for troubleshooting or development.
   - `./run_watcher_{dev|prod}.sh -h` to see all running options.

8. Monitor Watcher activity:
   ```bash
   tail watcher-{dev|prod}.log
   ```
   By default, calling `./run_watcher_{dev|prod}.sh` deletes `watcher-{dev|prod}.log` and restarts the Watcher.

<details><summary>Startup script options</summary>

```
Usage: ./run_watcher.sh [COMMAND] [--conf PATH] [OPTIONS]

Commands:
  stop                   Stop the running watcher
  status                 Show watcher status

Options:
  -c, --conf PATH        Path to site config TOML   (default: /global/homes/n/nmdcda/nmdc_automation/TEST/site_configuration_nersc_TEST.toml)
  -i, --pidfile PATH     Path to PID file           (default: watcher-TEST.pid)
  -s, --hostfile PATH    Path to host name file     (default: host-TEST.last)
  -l, --logfile PATH     Path to log file           (default: watcher-TEST.log)
  -L, --logfull PATH     Path to full log file      (default: watcher-TEST_full.log)
  -m, --mute             Silence Slack notifs
  -t, --test             Run wrapper in test mode
  -ta, --actual           Run wrapper in test mode with watcher code
  -h, --help             Show this help message
```
</details>

---

## Processing a Study

When a GitHub ticket requests processing for a new study, follow this workflow:

### 1. Get the Study ID

Note the study ID from the GitHub ticket (e.g., `nmdc:sty-11-hht5sb92`).

### 2. Check Workflow Status

Run the study report script to see which Data Generations are complete and which are missing workflow executions:

```bash
python nmdc_automation/run_process/run_report.py study-report \
    site_configuration_nersc_prod.toml \
    nmdc:sty-11-hht5sb92
```

Or use the alias if you're on Perlmutter as `nmdcda`:

```bash
study-report nmdc:sty-11-hht5sb92
```

The report shows:
- How many Data Generations are complete vs. incomplete
- Which Data Generation IDs are missing expected workflow executions
- Categories of incomplete runs (grouped by workflow execution and job types)

See [Using the Study Report Script](docs/README_troubleshooting.md#using-the-study-report-script) for detailed output examples.

### 3. Take Action Based on Results

**If Data Generations are missing jobs entirely** (no workflow executions or jobs exist):

1. Add the Data Generation IDs to `allow.lst` in the Scheduler (see [Running the Scheduler](#running-the-scheduler-on-nersc-rancher2)).
2. Restart the Scheduler — it will create jobs for these IDs on the next cycle.

**If jobs exist but are stuck in a claimed state:**

Use the [API release endpoint](https://api.microbiomedata.org/docs#/jobs/release_job_jobs__job_id__release_post) to release them back to the queue. See [Releasing Jobs](docs/README_troubleshooting.md#releasing-jobs) for details.

**If jobs failed in JAWS:**

Check the JAWS status and Watcher state file to diagnose the failure. See [Job Failures](docs/README_troubleshooting.md#job-failures) for troubleshooting steps.

**If the situation is ambiguous or requires deeper investigation:**

Use the MongoDB aggregation query to see the complete picture of which workflow executions and jobs exist for each Data Generation. See [Interpreting Workflow Status](docs/README_troubleshooting.md#interpreting-workflow-status) for a detailed decision tree.

---

## Reference: Job & State Records

### Job Document Schema

Jobs are stored in the MongoDB `jobs` collection. Query by `was_informed_by` to find all jobs associated with a specific DataGeneration ID:

```js
db.getCollection("jobs").find({
    "config.was_informed_by": "nmdc:omprc-11-sdyccb57"
})
```

<details><summary>Example job document</summary>

```json
{
    "workflow": {
        "id": "Metagenome Assembly: v1.0.9"
    },
    "id": "nmdc:9380c834-fab7-11ef-b4bd-0a13321f5970",
    "created_at": "2025-03-06T18:19:43.000+0000",
    "config": {
        "git_repo": "https://github.com/microbiomedata/metaAssembly",
        "release": "v1.0.9",
        "wdl": "jgi_assembly.wdl",
        "activity_id": "nmdc:wfmgas-12-k8dxr170.1",
        "activity_set": "workflow_execution_set",
        "was_informed_by": "nmdc:omprc-11-sdyccb57",
        "trigger_activity": "nmdc:wfrqc-12-dvn15085.1",
        "iteration": 1,
        "input_prefix": "jgi_metaAssembly",
        "inputs": {
            "input_files": "https://data.microbiomedata.org/data/nmdc:omprc-11-sdyccb57/nmdc:wfrqc-12-dvn15085.1/nmdc_wfrqc-12-dvn15085.1_filtered.fastq.gz",
            "proj": "nmdc:wfmgas-12-k8dxr170.1",
            "shortRead": false
        },
        "input_data_objects": [],
        "activity": {},
        "outputs": []
    },
    "claims": []
}
```
</details>

Key fields:

| Field | Description |
|---|---|
| `config.was_informed_by` | DataGeneration ID that is the root of this job |
| `config.trigger_activity` | WorkflowExecution ID that triggered this job |
| `config.inputs` | Inputs passed to the job |
| `claims` | Workers that have claimed the job. Empty = available to claim. |

<details><summary>Example claim entry</summary>

```json
{
    "op_id": "nmdc:sys0z232qf64",
    "site_id": "NERSC"
}
```

`op_id` is the operation ID and `site_id` is the site processing the job.
</details>

---

### Watcher State File

The Watcher maintains a state file with job configuration, metadata, and status. The file location is defined in the site config. For dev: `/global/cfs/cdirs/m3408/var/dev/agent.state`.

<details><summary>Example state file entry</summary>

```json
{
    "workflow": {
        "id": "Metagenome Assembly: v1.0.9"
    },
    "created_at": "2025-03-06T18:19:43",
    "config": {
        "git_repo": "https://github.com/microbiomedata/metaAssembly",
        "release": "v1.0.9",
        "wdl": "jgi_assembly.wdl",
        "activity_id": "nmdc:wfmgas-12-k8dxr170.1",
        "activity_set": "workflow_execution_set",
        "was_informed_by": "nmdc:omprc-11-sdyccb57",
        "trigger_activity": "nmdc:wfrqc-12-dvn15085.1",
        "iteration": 1,
        "input_prefix": "jgi_metaAssembly",
        "inputs": {
            "input_files": "https://data.microbiomedata.org/data/nmdc:omprc-11-sdyccb57/nmdc:wfrqc-12-dvn15085.1/nmdc_wfrqc-12-dvn15085.1_filtered.fastq.gz",
            "proj": "nmdc:wfmgas-12-k8dxr170.1",
            "shortRead": false
        },
        "input_data_objects": [],
        "activity": {},
        "outputs": []
    },
    "claims": [],
    "opid": "nmdc:sys0z232qf64",
    "done": true,
    "start": "2025-03-06T19:24:52.176365+00:00",
    "jaws_jobid": "0b138671-824d-496a-b681-24fb6cb207b3",
    "last_status": "Failed",
    "nmdc_jobid": 147004,
    "failed_count": 3
}
```
</details>

Additional fields beyond the job document:

| Field | Description |
|---|---|
| `done` | Boolean — whether the job has completed (successfully or not) |
| `jaws_jobid` | Job ID in the JAWS service |
| `last_status` | Last known status, updated by the Watcher |
| `failed_count` | Number of times this job has failed |

---

### MongoDB Queries

Query completed workflow executions by DataGeneration ID:

```js
db.getCollection("workflow_execution_set").find({
    "was_informed_by": "nmdc:omprc-11-sdyccb57"
})
```

For more complex status reporting queries, see [Checking Workflow Status](docs/README_troubleshooting.md#checking-workflow-status).

---

### JAWS

JAWS is the Cromwell-based service that executes jobs at NERSC. Documentation: [jaws-docs.readthedocs.io](https://jaws-docs.readthedocs.io/en/latest/).

With the `jaws_jobid` from an `agent.state` entry, check job status:

```bash
jaws status 109288
```

<details><summary>Example JAWS status response</summary>

```json
{
  "compute_site_id": "nmdc",
  "cpu_hours": null,
  "cromwell_run_id": "0fddc559-833e-4e14-9fa5-1e3d485b232d",
  "id": 109288,
  "input_site_id": "nmdc",
  "result": null,
  "status": "running",
  "status_detail": "The run is being executed; you can check `tasks` for more detail",
  "submitted": "2025-05-01 11:22:45",
  "tag": "nmdc:dgns-11-sm8wyy89/nmdc:wfrqc-11-7fgdsy18.1",
  "team_id": "nmdc",
  "updated": "2025-05-01 11:40:44",
  "user_id": "nmdcda",
  "workflow_name": "nmdc_rqcfilter",
  "workflow_root": "/pscratch/sd/n/nmjaws/nmdc-prod/cromwell-executions/nmdc_rqcfilter/0fddc559-833e-4e14-9fa5-1e3d485b232d"
}
```
</details>

---

## Handling Failed Jobs

By default, the Watcher retries a failed job once via `jaws submit`. If it fails again, the Watcher marks the job as `done` with `last_status: Failed`.

**Transient download failures** — If a job failed due to an incomplete data download, retry with:
```bash
jaws download $jaws_jobid
```

**System errors requiring resubmission** — If the JAWS job itself cannot be resubmitted, use the [API release endpoint](https://api.microbiomedata.org/docs#/jobs/release_job_jobs__job_id__release_post) to mark the claimed job as available and trigger a resubmission. This increments the `claims` array in the job record by 1.

For step-by-step troubleshooting of failed jobs and other common issues, see the [Troubleshooting Guide](docs/README_troubleshooting.md).
