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
      - [Watcher Set-Up and Configuration](#watcher-set-up-and-configuration)
    - [Running the Watcher on NERSC Perlmutter](#running-the-watcher-on-nersc-perlmutter)
      - [Check the Watcher Status](#check-the-watcher-status)
      - [Running the Watcher](#running-the-watcher)
      - [Monitoring the Watcher](#monitoring-the-watcher)
      - [JAWS](#jaws)
        - [NMDC Database](#nmdc-database)
        - [Watcher State File](#watcher-state-file)
      - [Handling Failed Jobs](#handling-failed-jobs)


## Installation

### Requirements

- mongodb-community needs to be installed and running on the local machine
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

### Running the Scheduler on NERSC Rancher2

The Scheduler is a Dockerized application running on [Rancher](https://rancher2.spin.nersc.gov). To initialize the Scheduler for new DataGeneration IDs, the following steps:

1. On Rancher, go to `Deployments`, select `Production` from the clusters list, and find the Scheduler in either `nmdc` or `nmdc-dev`
   1. Check that the image is running the latest production version for prod or the desired release candidate for testing for dev. 
   2. Refer to [Release Documentation](https://github.com/microbiomedata/infra-admin/blob/main/releases/nmdc-automation.md) for more information
2. Click on the Scheduler and select `run shell`
3. In the shell, `cd /conf`
4. Update the file `allow.lst` with the Data Generation IDs that you want to schedule
   1. Copy the list of data-generation IDs to you clipboard
   2. In the shell, delete the existing allow list `rm allow.lst`
   3. Replace the file with your copied list:
      1. `cat >allow.lst`
      2. Paste your IDs `command-v`
      3. Ensure a blank line at the end with a `return` 
      4. Terminate the `cat` command using `control-d`
5. The default log level is `INFO` if you want to change it to `DEBUG` for more verbose logging, run the following command:
   1. `export NMDC_LOG_LEVEL=DEBUG`
6. Restart the scheduler. In the shell, in `/conf`:  `./run_scheduler.sh`
   1. If running tests on `dev`, make sure to check `./run_scheduler.sh -h` for options. 
7. Ensure the scheduler is running by checking `sched.log`
   1. By default, calling `./run_scheduler.sh` will delete `sched.log` and restart the Scheduler. 


#### Watcher Set-Up and Configuration

1. Ensure you have the desired version of `nmdc_automation` code.
   1. `cd nmdc_automation`
   2. `git status` 
   3. `git fetch --all --prune`
   4. `git checkout tags/[release-version]`
2. Setup NMDC automation environment with `conda` and `poetry`. 
   1. load conda: `eval "$__conda_setup"` 
   3. in the `nmdc_automation` directory, install the nmdc_automation project with `poetry install`
   4. `eval $(poetry env activate)` to use the environment
        <details><summary>Hint</summary>
            
        If you can't remember the command for step 4, there's an alias set in the nmdcda `~/.bashrc file` that allows you to just call `poetry-shell`:

            alias poetry-shell='eval $(poetry env activate)'

        </details>

<details><summary>Example Setup:</summary>

```bash
(nersc-python) nmdcda@perlmutter:login38:~> pwd
/global/homes/n/nmdcda
(nersc-python) nmdcda@perlmutter:login38:~> cd nmdc_automation/dev/
(nersc-python) nmdcda@perlmutter:login38:~/nmdc_automation/dev> eval "$__conda_setup"
(base) nmdcda@perlmutter:login38:~/nmdc_automation/dev> cd nmdc_automation/
(base) nmdcda@perlmutter:login38:~/nmdc_automation/dev/nmdc_automation> poetry install
Installing dependencies from lock file

No dependencies to install or update

Installing the current project: nmdc-automation (0.1.0)
(base) nmdcda@perlmutter:login06:~/nmdc_automation/dev/nmdc_automation> eval $(poetry env activate)
(nmdc-automation-py3.11) (base) nmdcda@perlmutter:login06:~/nmdc_automation/dev/nmdc_automation>
```
</details>


The `eval $(poetry env activate)` command will activate the environment for the current shell session. 
Environment `(nmdc-automation-py3.11)` will be displayed in the prompt.

### Running the Watcher on NERSC Perlmutter

The watcher is a python application which runs on a login node on Perlmutter. 
The following instructions all assume the user is logged in as user `nmdcda@perlmutter.nersc.gov`

1. Get an ssh key - in your home directory: `./sshproxy.sh -u <your_nersc_username> -c nmdcda`
2. Log in using the key `ssh -i .ssh/nmdcda nmdcda@perlmutter.nersc.gov`

Watcher code and config files can be found in `/global/homes/n/nmdcda/nmdc_automation/[dev/prod]`, respectively.

#### Check the Watcher Status

1. Check the last node the watcher was running on via `host-[dev/prod].last`
   
    <details><summary>example</summary>

    ```shell
    (base) nmdcda@perlmutter:login07:~> cd nmdc_automation/[dev/prod]
    (base) nmdcda@perlmutter:login07:~/nmdc_automation/[dev/prod]> cat host-[dev/prod].last
    login24
    ```
    </details>

2. ssh to that node
   
    <details><summary>example</summary>

    ```shell
    (base) nmdcda@perlmutter:login07:~/nmdc_automation/[dev/prod]> ssh login24
    ```
    </details>

1. Check for the watcher process using `ps aux`

    <details><summary>example</summary>
    ```shell
    (base) nmdcda@perlmutter:login24:~> ps aux | grep watcher
    nmdcda    115825  0.0  0.0   8236   848 pts/94   S+   09:33   0:00 grep watcher
    nmdcda   2044781  0.4  0.0 146420 113668 ?       S    Mar06   5:42 python -m nmdc_automation.run_process.run_workflows watcher --config /global/homes/n/nmdcda/nmdc_automation/prod/site_configuration_nersc_prod.toml --jaws daemon
    nmdcda   2044782  0.0  0.0   5504   744 ?        S    Mar06   0:00 tee -a watcher-prod.log
    ````
    </details>

2. **IF** we are going to shut down the Watcher (without restarting), we need to kill the existing process
    ```shell
    (base) nmdcda@perlmutter:login24:~> ./run_watcher_[dev/prod].sh cleanup
    ```
> [!NOTE]
> This will also terminate the `tee` process that is writing to the log file.
> To restart the Watcher with older versions of the `./run.sh script`, manual termination of the existing process was necessary with `kill -9 2044781`. However, the new `run_watcher.sh` script now handles killing and restarting the Watcher. 



#### Running the Watcher

We run the Watcher using `nohup` (No Hangup) - this prevents the Watcher process from being terminated
when the user's terminal session ends.  This will cause stdout and stderr to be written to a file
names `nohup.out` in addition to being written to the `watcher-[dev/prod].log` file.  

1. change to the working `prod` or `dev` directory
- `/global/homes/n/nmdcda/nmdc_automation/prod`
- `/global/homes/n/nmdcda/nmdc_automation/dev`
1. `rm nohup.out` (Long term logging is captured in the `watcher-[dev/prod].log` file, which is retained)
2. `nohup ./run_watcher_dev.sh &` (for dev) OR `nohup ./run_watcher_prod.sh &` (for prod)
    
#### Monitoring the Watcher

Same process as as [Checking the Watcher Status](#check-the-watcher-status)

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
