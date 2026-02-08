[![CI](https://github.com/microbiomedata/nmdc_automation/actions/workflows/blt.yml/badge.svg)](https://github.com/microbiomedata/nmdc_automation/actions/workflows/blt.yml)
![Tests](./badges/tests.svg)
![Coverage](./badges/coverage.svg)


<!-- Pytest Coverage Comment:Begin -->
<!-- Pytest Coverage Comment:End -->

# nmdc_automation

An automation framework for running sequential metagenome analysis jobs and making the outputs
available as metadata in the NMDC database, and data objects on the NMDC data portal.

## Table of Contents
- [nmdc\_automation](#nmdc_automation)
  - [Table of Contents](#table-of-contents)
  - [Installation](#installation)
    - [Requirements](#requirements)
    - [MongoDB Installation](#mongodb-installation)
    - [Installation](#installation-1)
  - [Overview](#overview)
    - [System Configuration](#system-configuration)
      - [Site Config](#site-config)
      - [Workflow Definitions](#workflow-definitions)
  - [Quick Start](#quick-start)
    - [Running the Scheduler on NERSC Rancher2](#running-the-scheduler-on-nersc-rancher2)
    - [Running the Watcher on NERSC Perlmutter](#running-the-watcher-on-nersc-perlmutter)
      - [JAWS](#jaws)
        - [NMDC Database](#nmdc-database)
        - [Watcher State File](#watcher-state-file)
      - [Handling Failed Jobs](#handling-failed-jobs)


## Installation

### Requirements

- `mongodb-community` needs to be installed and running on the local machine
- Python 3.11 or later
- Poetry version 2.2.1


Poetry Installation instructions can be found [Here](https://python-poetry.org/docs/#installing-with-pipx)


### MongoDB Installation

Install MongoDB using Homebrew on MacOS:

```bash
brew tap mongodb/brew
brew install mongodb-community
brew services start mongodb-community
```

Full Mongodb installation instructions for Mac can be found [here](https://docs.mongodb.com/manual/tutorial/install-mongodb-on-os-x/)

 Ensure that the mongodb service is running:
```bash
brew services start mongodb-community
```

### Installation

1. Clone the repository
    ```bash
    git clone https://github.com/microbiomedata/nmdc_automation.git
    ```

2. Install the required packages
    ```bash
    cd nmdc_automation  
    poetry install
    ```

3. Activate the poetry environment 
    ```  
    eval $(poetry env activate)
    ```
    

4. Run the tests
    ```bash
    make test
    ```



## Overview

### System Configuration

#### Site Config
Site-specific configuration is provided by a `.toml` file and defines some parameters that are used
across the workflow process including

1. URL and credentials for NMDC API
2. Staging and Data filesystem locations for the site
3. Job Runner service URLs
4. Path to the state file

#### Workflow Definitions
Workflow definitions in a `.yaml` file describing each analysis step, specifying:

1. Name, type, version, WDL and git repository for each workflow
2. Inputs, Outputs and Workflow Execution steps
3. Data Object Types, description and name templates for processing workflow output data

**Developer details:** For architecture, implementation internals, and an extended developer quickstart (algorithm, classes, version-compatibility rules, and testing), see [developer documention](docs/README_developers.md).


## Quick Start

We run both the Scheduler and the Watcher using `nohup` (No Hangup) - this prevents the process from being terminated when the user's terminal session ends.  This will cause `stdout` and `stderr` to be written to a file named `nohup.out` in addition to being written to the per-session `*[dev/prod].log` and running `*[dev/prod]_full.log` files. The `nohup.out` files are manually cleared by the user with each (re)start of the processes while the per session logs are automatically overwritten every time.   

### Running the Scheduler on NERSC Rancher2

The Scheduler is a Dockerized application running on [Rancher](https://rancher2.spin.nersc.gov). To initialize the Scheduler for new DataGeneration IDs, the following steps:

1. On Rancher, go to `Deployments`, select `Production` from the clusters list, and find the Scheduler in either `nmdc` or `nmdc-dev`
   1. Check that the image is running the latest production version for prod or the desired release candidate for testing for dev. 
   2. Refer to [Release Documentation](https://github.com/microbiomedata/infra-admin/blob/main/releases/nmdc-automation.md) for more information
2. Click on the Scheduler and select `run shell`
3. `cd /conf` in shell for working directory. 
   1. All following user actions will be in this directory.
4. Update the file `allow.lst` with the Data Generation IDs that you want to schedule
   1. Copy the list of data generation IDs to you clipboard
   2. In the shell, delete the existing allow list `rm allow.lst`
   3. Replace the file with your copied list:
      1. `cat > allow.lst` to start writing to file
      2. `command-v` to paste IDs
      3. `return` to ensure a blank line at the end 
      4. `control-d` to terminate the `cat` command 
5. `./run_scheduler.sh status` to see if there's anything running.
   1. `./run_scheduler.sh stop` to manually terminate the process without restarting.
6. Start or restart the Scheduler by calling the startup script with `nohup`.
   1. `rm nohup.out` to clear the nohup log. This is optional, but recommended since there's already the running `*_full.log`
   2. `nohup ./run_scheduler.sh &` 
      1. Only run without `nohup` for troubleshooting and development.
      2. `./run_scheduler.sh -h` to see more running options
      3. `[-d/--debug ]` for more verbose logging
7. `[cat/tail] sched-[dev/prod].log` to see Scheduler activity.
   1. By default, calling `./run_scheduler.sh` will delete `sched-[dev/prod].log` and restart the Scheduler. 


### Running the Watcher on NERSC Perlmutter

The Watcher is a python application which runs on a login node on Perlmutter. 
The following instructions all assume the user is logged in as user `nmdcda@perlmutter.nersc.gov`. For setup instructions, please refer to [startup documentation](docs/README_troubleshooting.md).

Watcher code and config files can be found in `/global/homes/n/nmdcda/nmdc_automation/[dev/prod]`, respectively. 


1. Navigate to the correct login node where the Watcher was last run
   1. `cat ~/nmdc_automation/[dev/prod]/host-[dev/prod].last`
   2. `ssh login[node #]`
2. Ensure you have the desired version of `nmdc_automation` code.
   1. `cd ~/nmdc_automation/[dev/prod]/nmdc_automation` to access the repository
   2. `git status` to see which tag.
   3. `git fetch --all --prune`
   4. `git checkout tags/[release-version]` to access desired version.
3. Setup NMDC automation environment with `conda` and `poetry`. 
   1. `eval "$__conda_setup"` to load conda.
   2. `poetry install` to install the nmdc_automation project 
   3. `eval $(poetry env activate)` to use the environment.
      1. This will activate the environment for the current shell session. 
      2. Environment `(nmdc-automation-py3.11)` will be displayed in the prompt.
   

    <details><summary>Example Setup:</summary>

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


    <details><summary>Hint</summary>

    A function has been set within the `~/.bashrc` of the `nmdcda` account to quickly set up the environment once you are on the correct node / host. This way, you can call `auto-[dev/prod]`, and  steps 3-4 will automatically be run for you. 
    ```bash
    auto-[dev/prod]() {
        eval "$__conda_setup"
        cd /global/homes/n/nmdcda/nmdc_automation/[dev/prod]/nmdc_automation
        poetry install
        eval $(poetry env activate)
        cd /global/homes/n/nmdcda/nmdc_automation/[dev/prod]/
    }
    ```

    There's also an alias set that allows you to call `poetry-shell`:

    ```bash
    alias poetry-shell='eval $(poetry env activate)'
    ```
    </details>


4. Change to the working `prod` or `dev` directory
   - `/global/homes/n/nmdcda/nmdc_automation/prod`
   - `/global/homes/n/nmdcda/nmdc_automation/dev`
   1. Running the command in Step 3's hint automatically navigates to the correct environment. However, it must be run right after navigating to the correct login node. 
5. Check for the watcher process using `./run_watcher_[dev/prod].sh status` or `ps aux`.

    <details><summary>example check status</summary>

    ```shell
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
    42     "status_detail": "The run is complete.",
    42     "status": "done",
    ```

    ```shell
    (nmdc-automation-py3.11) (base) nmdcda@perlmutter:login17:~/nmdc_automation/prod> ps aux | grep nmdcda | grep watcher
    nmdcda     78922  0.0  0.0   8236   844 pts/29   S+   21:06   0:00 grep watcher
    nmdcda   1429309  0.0  0.0   7312  3784 ?        S    15:43   0:00 /bin/bash ./run_watcher_prod.sh
    nmdcda   1429340  0.0  0.0   5536   824 ?        S    15:43   0:01 tail -n 0 -F watcher-prod.log
    nmdcda   1429341  0.0  0.0   7684  3436 ?        S    15:43   0:04 /bin/bash ./run_watcher_prod.sh
    nmdcda   1429358  1.7  0.2 1249168 1224036 ?     S    15:43   5:44 python -u -m nmdc_automation.run_process.run_workflows watcher --config /global/homes/n/nmdcda/nmdc_automation/prod/site_configuration_nersc_prod.toml daemon
    nmdcda   1429359  0.0  0.0   7312  2068 ?        S    15:43   0:00 /bin/bash ./run_watcher_prod.sh
    nmdcda   1429360  0.0  0.0   5504   740 ?        S    15:43   0:00 tee -a watcher-prod.log watcher-prod_full.log
    ````
    </details>

6. **IF** we are going to shut down the Watcher (without restarting), we need to kill the existing process. You don't need the poetry environment activated, but you need to be on the correct login node. 
    ```shell
    nmdcda@perlmutter:login17:~/nmdc_automation/prod> ./run_watcher_[dev/prod].sh stop
    ```
    1. This will terminate all 6 processes seen in Step 4. 
    2. To restart the Watcher with older versions of the `./run.sh script`, manual termination of the existing process was necessary with `kill -9 2044781`. However, the new `run_watcher_[dev/prod].sh` script now handles killing and restarting the Watcher. 

7. Start or restart the Watcher by calling the startup script with `nohup`.
   1. `rm nohup.out` to clear the nohup log. This is optional, but recommended since there's already the running `*_full.log`
   2. `nohup ./run_watcher_[dev/prod].sh &` 
      1. Only run without `nohup` for troubleshooting and development.
      2. `./run_watcher_[dev/prod].sh -h` to see more running options
8. `[cat/tail] watcher-[dev/prod].log` to see Watcher activity.
   1. By default, calling `./run_watcher_[dev/prod].sh` will delete `watcher-[dev/prod].log` and restart the Watcher. 


#### JAWS

JAWS is a Cromwell-based service that runs jobs on NERSC and other compute resources.
Documentation can be found [here](https://jaws-docs.readthedocs.io/en/latest/).

With the `jaws_jobid` from the `agent.state` files, you can check the status of the job in the JAWS service

<details><summary>JAWS Status call:</summary>

```shell
> jaws status 109288
{
  "compute_site_id": "nmdc",
  "cpu_hours": null,
  "cromwell_run_id": "0fddc559-833e-4e14-9fa5-1e3d485b232d",
  "id": 109288,
  "input_site_id": "nmdc",
  "json_file": "/tmp/tmpeoq9a5p_.json",
  "output_dir": null,
  "result": null,
  "status": "running",
  "status_detail": "The run is being executed; you can check `tasks` for more detail",
  "submitted": "2025-05-01 11:22:45",
  "tag": "nmdc:dgns-11-sm8wyy89/nmdc:wfrqc-11-7fgdsy18.1",
  "team_id": "nmdc",
  "updated": "2025-05-01 11:40:44",
  "user_id": "nmdcda",
  "wdl_file": "/tmp/tmpq0l3fk0n.wdl",
  "workflow_name": "nmdc_rqcfilter",
  "workflow_root": "/pscratch/sd/n/nmjaws/nmdc-prod/cromwell-executions/nmdc_rqcfilter/0fddc559-833e-4e14-9fa5-1e3d485b232d"
}
```
</details>

##### NMDC Database

1. Query the `jobs` table in the NMDC database based on `was_informed_by` a specific DataGeneration ID
    ```shell 
    db.getCollection("jobs").find({
        "config.was_informed_by": "nmdc:omprc-11-sdyccb57"
    })
    ```

    Similarly, you can query `workflow_executions` to find results based on `was_informed_by` a specific DataGeneration ID

    ```shell 
    db.getCollection("workflow_execution_set").find({
        "was_informed_by": "nmdc:omprc-11-sdyccb57"
    })
    ``` 

2. Job document example
    
    <details><summary>Example database entry</summary>

    ```json
    {
        "workflow" : {
            "id" : "Metagenome Assembly: v1.0.9"
        },
        "id" : "nmdc:9380c834-fab7-11ef-b4bd-0a13321f5970",
        "created_at" : "2025-03-06T18:19:43.000+0000",
        "config" : {
            "git_repo" : "https://github.com/microbiomedata/metaAssembly",
            "release" : "v1.0.9",
            "wdl" : "jgi_assembly.wdl",
            "activity_id" : "nmdc:wfmgas-12-k8dxr170.1",
            "activity_set" : "workflow_execution_set",
            "was_informed_by" : "nmdc:omprc-11-sdyccb57",
            "trigger_activity" : "nmdc:wfrqc-12-dvn15085.1",
            "iteration" : 1,
            "input_prefix" : "jgi_metaAssembly",
            "inputs" : {
                "input_files" : "https://data.microbiomedata.org/data/nmdc:omprc-11-sdyccb57/nmdc:wfrqc-12-dvn15085.1/nmdc_wfrqc-12-dvn15085.1_filtered.fastq.gz",
                "proj" : "nmdc:wfmgas-12-k8dxr170.1",
                "shortRead" : false
            },
            "input_data_objects" : [],
            "activity" : {},
            "outputs" : []
        },
        "claims" : [ ]
    }
    ```
    </details>

Things to note:
- `config.was_informed_by` is the DataGeneration ID that is the root of this job
- `config.trigger_activity` is the WorkflowExecution ID that triggered this job
- `config.inputs` are the inputs to the job
- `claims` a list of workers that have claimed the job. If this list is empty, the job is available to be claimed. If the list is not empty, the job is being processed by a worker

  <details><summary>Example Claim</summary>

    ```json
    {
        "op_id" : "nmdc:sys0z232qf64",
        "site_id" : "NERSC"
    }
    ```
  This refers to the `operation` and `site` that is processing the job.

  </details>


##### Watcher State File

The Watcher maintains a state file with job configuration, metadata and status information. The location of the 
state file is defined in the site configuration file. For dev this location is:
`/global/cfs/cdirs/m3408/var/dev/agent.state`


<details><summary>Example State File Entry</summary>

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

Similar to a `jobs` record, with these additional things to note:
- `done` is a boolean indicating if the job is complete
- `jaws_jobid` is the job ID from JAWS service
- `last_status` is the last known status of the job - this is updated by the watcher
- `failed_count` is the number of times the job has failed



#### Handling Failed Jobs

By default, the Watcher will retry a failed job 1 additional time via `jaws submit`. 
If the job fails again, the Watcher will mark the job as `done` and update the status to `Failed`.

Some things to note:

For jobs that have failed  with a transient incomplete data download, these may be resolved by invoking the `jaws download $jaws_jobid` command

For jobs that may have failed due to system errors and need to be resubmitted, use the [API release endpoint](https://api.microbiomedata.org/docs#/jobs/release_job_jobs__job_id__release_post) to mark a claimed job as failed and have JAWS resubmit the job if the JAWS job itself cannot be resubmitted. This will increase the `claims` array in the `jobs` record by 1. 
