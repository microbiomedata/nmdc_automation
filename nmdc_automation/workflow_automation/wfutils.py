#!/usr/bin/env python

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from tenacity import retry, wait_exponential, stop_after_attempt
from typing import Any, Dict, List, Optional, Union
import pytz
import requests
import zipfile

from nmdc_automation.config import SiteConfig
from nmdc_automation.models.nmdc import DataObject, WorkflowExecution, workflow_process_factory

from nmdc_schema.nmdc import DataCategoryEnum

from jaws_client import api as jaws_api
from jaws_client.config import Configuration as jaws_Configuration

DEFAULT_MAX_RETRIES = 1

logging_level = os.getenv("NMDC_LOG_LEVEL", logging.INFO)
logging.basicConfig(
    level=logging_level, format="%(asctime)s %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

class JobRunnerABC(ABC):
    """Abstract base class for job runners"""

    # States that indicate a job is in some active state and does not need to be submitted
    NO_SUBMIT_STATES = [
        "submitted",  # job is already submitted but not running
        "running",  # job is already running
        "succeeded",  # job succeeded
        "aborting"  # job is in the process of being aborted
        "on hold",  # job is on hold and not running. It can be manually resumed later
    ]

    def __init__(self, site_config: SiteConfig, workflow: "WorkflowStateManager"):
        self.config = site_config
        self.workflow = workflow

    @abstractmethod
    def submit_job(self) -> str:
        """ Submit a job """
        pass

    @abstractmethod
    def get_job_status(self) -> str:
        """ Get the status of a job """
        pass

    @abstractmethod
    def get_job_metadata(self) -> Dict[str, Any]:
        """ Get metadata for a job """
        pass

    @property
    @abstractmethod
    def job_id(self) -> Optional[str]:
        """ Get the job id """
        pass

    @property
    @abstractmethod
    def outputs(self) -> Dict[str, str]:
        """ Get the outputs """
        pass

    @property
    @abstractmethod
    def metadata(self) -> Dict[str, Any]:
        """ Get the metadata """
        pass

    @property
    @abstractmethod
    def max_retries(self) -> int:
        """ Get the maximum number of retries """
        pass


class JawsRunner(JobRunnerABC):
    """ Job runner for J.A.W.S"""

    DEFAULT_JOB_SITE = 'nmdc'
    JAWS_NO_SUBMIT_STATES = [
        "created",          # The Run was accepted and a run_id assigned.
        "upload queued",    # The Run's input files are waiting to be transferred to the compute-site.
        "uploading",        # Your Run's input files are being transferred to the compute-site.
        "upload failed",    # The transfer of your run to the compute-site failed.
        "upload inactive",  # Globus transfer stalled.
        "upload complete",  # Your Run's input files have been transferred to the compute-site successfully.
        "ready",            # The Run has been transferred to the compute-site.
        "submitted",        # The run has been submitted to Cromwell and tasks should start to queue within moments.
        "submission failed", # The run was submitted to Cromwell but rejected due to invalid input.
        "queued",           # At least one task has requested resources but no tasks have started running yet.
        "running",          # The run is being executed; you can check `tasks` for more detail.
        "succeeded",        # The run has completed successfully.
        "complete",         # Supplementary files have been written to the run's output dir.
        "finished",         # The task-summary has been published to the performance metrics service.
        "cancelling",       # Your run is in the process of being canceled.
        "cancelled",        # The run was cancelled by either the user or an admin.
        "download queued",  # Your Run's output files are waiting to be transferred from the compute-site.
        "downloading",      # The Run's output files are being transferred from the compute-site.
        "download failed",  # The Run's output files could not be transferred from the compute-site.
        "download inactive", # Globus transfer stalled.
        "download complete", # Your Run's output (succeeded or failed) have been transferred to the team outdir.
        "download skipped",  # The run was not successful so the results were not downloaded.
        "done",             # The run is complete.
    ]

    def __init__(self,
                 site_config: SiteConfig, workflow: "WorkflowStateManager", jaws_api: jaws_api.JawsApi,
                 job_metadata: Dict[str, Any] = None, job_site: str = None) -> None:
        super().__init__(site_config, workflow)
        self.jaws_api = jaws_api
        self._metadata = {}
        if job_metadata:
            self._metadata = job_metadata
        self.job_site = job_site or self.DEFAULT_JOB_SITE
        self.no_submit_states = self.JAWS_NO_SUBMIT_STATES + self.NO_SUBMIT_STATES


    @retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(2))
    def submit_job(self, force: bool = False) -> Optional[int]:
        """
        Submit a job to J.A.W.S. Update the workflow state with the job id and status.
        :param force: if True, submit the job even if it is in a state that does not require submission
        :return: {'run_id': 'int'}
        """
        status = self.workflow.last_status
        if status and status.lower() in self.no_submit_states and not force:
            logger.info(f"Job {self.job_id} in state {status}, skipping submission")
            return None
        cleanup_zip_dirs = []
        try:
            files = self.workflow.generate_submission_files(for_jaws=True)

            # Temporary fix to handle the fact that the JAWS API does not handle the sub argument and the zip file
            if 'sub' in files:
                extract_dir = os.path.dirname(files["sub"])
                with zipfile.ZipFile(files["sub"], 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
                cleanup_zip_dirs.append(extract_dir)

            # Validate
            validation_resp = self.jaws_api.validate(
                shell_check=False, wdl_file=files["wdl_file"],
                inputs_file=files["inputs"]
            )
            if validation_resp["result"] != "succeeded":
                logger.error(f"Failed to Validate Job: {validation_resp}")
                raise Exception(f"Failed to Validate Job: {validation_resp}")
            else:
                logger.info(f"Validation Succeeded: {validation_resp}")

            tag_value = self.workflow.was_informed_by + "/" + self.workflow.workflow_execution_id
            # Submit to J.A.W.S
            logger.info(f"Submitting job to JAWS with tag: {tag_value}")
            logger.info(f"Site: {self.job_site}")
            logger.info(f"Inputs: {files['inputs']}")
            logger.info(f"WDL: {files['wdl_file']}")
            logger.info(f"Sub: {files['sub']}")

            response = self.jaws_api.submit(
                wdl_file=files["wdl_file"],
                sub=files["sub"],
                inputs=files["inputs"],
                tag = tag_value,
                site = self.job_site
            )
            self.job_id = response['run_id']
            logger.info(f"Submitted job {response['run_id']}")

            # update workflow state
            self.workflow.done = False
            self.workflow.update_state({"start": datetime.now(pytz.utc).isoformat()})
            self.workflow.update_state({"jaws_jobid": self.job_id})
            self.workflow.update_state({"last_status": "Submitted"})

            return self.job_id

        except Exception as e:
            logger.error(f"Failed to Submit Job: {e}")
            raise e

        finally:
            _cleanup_dirs(cleanup_zip_dirs)


    @retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(3))
    def get_job_metadata(self) -> Dict[str, Any]:
        """ Get metadata for a job. In JAWS this is the response from the status call and the
        logical names and file paths for the outputs specified in outputs.json """
        metadata = self.jaws_api.status(self.job_id)
        # load output_dir / outputs.json file if the job is done and the outputs are available
        if "output_dir" in metadata and metadata["status"] == "done":
            output_dir = metadata["output_dir"]
            outputs_path = Path(output_dir) / "outputs.json"
            with open(outputs_path) as f:
                outputs = json.load(f)
                # output paths are relative to the output_dir
                for key, val in outputs.items():
                    # some values may be 'null' if the output was not generated
                    if val:
                        outputs[key] = str(Path(output_dir) / val)
                metadata["outputs"] = outputs
        # update cached metadata
        self.metadata = metadata
        return metadata

    @retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(3))
    def get_job_status(self) -> str:
        """
        Get the status of a job. In JAWS this is the response from the status call
        and the status and results keys.
        """
        logger.debug(f"Getting job status for job {self.job_id}")
        resp = self.jaws_api.status(self.job_id)
        # If the status is not 'done' then the job is still running
        if resp['status'] != 'done':
            return 'running'
        # If the status is 'done' then return the result key
        return resp['result']



    @property
    def job_id(self) -> Optional[int]:
        """
        Get the job id from the metadata if set or the workflow state
        """
        if self.metadata.get("id"):
            return self.metadata.get("id")
        return self.workflow.job_runner_id

    @job_id.setter
    def job_id(self, job_id: int):
        """ Set the job id in the metadata """
        self.metadata["id"] = job_id

    @property
    def outputs(self) -> Dict[str, str]:
        """ Get the outputs from the metadata """
        return self.metadata.get("outputs", {})

    @outputs.setter
    def outputs(self, outputs: Dict[str, str]):
        """ Set the outputs in the metadata """
        self.metadata["outputs"] = outputs

    @property
    def metadata(self) -> Dict[str, Any]:
        """ Get the metadata """
        return self._metadata

    @metadata.setter
    def metadata(self, metadata: Dict[str, Any]):
        """ Set the metadata """
        self._metadata = metadata

    def max_retries(self) -> int:
        """ Get the maximum number of retries - Set this at 1 for now """
        return DEFAULT_MAX_RETRIES

    @property
    def started_at_time(self) -> Optional[str]:
        """ Get the start time of the job """
        return self.metadata.get("submitted", None)

    @property
    def ended_at_time(self) -> Optional[str]:
        """ Get the end time of the job """
        return self.metadata.get("updated", None)


class CromwellRunner(JobRunnerABC):
    """Job runner for Cromwell"""
    LABEL_SUBMITTER_VALUE = "nmdcda"
    LABEL_PARAMETERS = ["release", "wdl", "git_repo"]

    def __init__(self, site_config: SiteConfig, workflow: "WorkflowStateManager", job_metadata: Dict[str, Any] = None,
                 max_retries: int = DEFAULT_MAX_RETRIES, dry_run: bool = False) -> None:
        """
        Create a Cromwell job runner.
        :param site_config: SiteConfig object
        :param workflow: WorkflowStateManager object
        :param job_metadata: metadata for the job
        :param max_retries: maximum number of retries for a job
        :param dry_run: if True, do not submit the job
        """
        super().__init__(site_config, workflow)
        self.service_url = self.config.cromwell_url
        self._metadata = {}
        if job_metadata:
            self._metadata = job_metadata
        self._max_retries = max_retries
        self.dry_run = dry_run


    def submit_job(self, force: bool = False) -> Optional[str]:
        """
        Submit a job to Cromwell. Update the workflow state with the job id and status.
        :param force: if True, submit the job even if it is in a state that does not require submission
        :return: the job id
        """
        status = self.workflow.last_status
        if status and status.lower() in self.NO_SUBMIT_STATES and not force:
            logger.info(f"Job {self.job_id} in state {status}, skipping submission")
            return None
        cleanup_files = []
        try:
            files = self.workflow.generate_submission_files()
            cleanup_files = list(files.values())
            if not self.dry_run:
                response = requests.post(self.service_url, files=files)
                response.raise_for_status()
                self.metadata = response.json()
                self.job_id = self.metadata["id"]
                logger.info(f"Submitted job {self.job_id}")

                metadata_dump = json.dumps(self.metadata, indent=2)
                logger.info("Metadata:")
                logger.info(metadata_dump)
            else:
                logger.info(f"Dry run: skipping job submission")
                self.job_id = "dry_run"

            logger.info(f"Job {self.job_id} submitted")
            start_time = datetime.now(pytz.utc).isoformat()
            # update workflow state
            self.workflow.done = False
            self.workflow.update_state({"start": start_time})
            self.workflow.update_state({"cromwell_jobid": self.job_id})
            self.workflow.update_state({"last_status": "Submitted"})
            return self.job_id
        except Exception as e:
            logger.error(f"Failed to submit job: {e}")
            raise e
        finally:
            _cleanup_files(cleanup_files)

    def get_job_status(self) -> str:
        """ Get the status of a job from Cromwell """
        if not self.workflow.job_runner_id:
            return "Unknown"
        status_url = f"{self.service_url}/{self.workflow.job_runner_id}/status"
        # There can be a delay between submitting a job and it
        # being available in Cromwell so handle 404 errors
        logger.debug(f"Getting job status from {status_url}")
        try:
            response = requests.get(status_url)
            response.raise_for_status()
            return response.json().get("status", "Unknown")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return "Unknown"
            raise e

    def get_job_metadata(self) -> Dict[str, Any]:
        """ Get metadata for a job from Cromwell """
        metadata_url = f"{self.service_url}/{self.job_id}/metadata"
        response = requests.get(metadata_url)
        response.raise_for_status()
        metadata = response.json()
        # update cached metadata
        self.metadata = metadata
        return metadata

    @property
    def job_id(self) -> Optional[str]:
        """ Get the job id from the metadata """
        return self.metadata.get("id", None)

    @job_id.setter
    def job_id(self, job_id: str):
        """ Set the job id in the metadata """
        self.metadata["id"] = job_id

    @property
    def outputs(self) -> Dict[str, str]:
        """ Get the outputs from the metadata """
        return self.metadata.get("outputs", {})

    @property
    def metadata(self) -> Dict[str, Any]:
        """ Get the metadata """
        return self._metadata

    @metadata.setter
    def metadata(self, metadata: Dict[str, Any]):
        """ Set the metadata """
        self._metadata = metadata

    @property
    def max_retries(self) -> int:
        return self._max_retries

    @property
    def started_at_time(self) -> Optional[str]:
        """ Get the start time of the job """
        return self.metadata.get("start", None)

    @property
    def ended_at_time(self) -> Optional[str]:
        """ Get the end time of the job """
        return self.metadata.get("end", None)


class WorkflowStateManager:
    CHUNK_SIZE = 1000000  # 1 MB
    GIT_RELEASES_PATH = "/releases/download"
    LABEL_SUBMITTER_VALUE = "nmdcda"
    LABEL_PARAMETERS = ["release", "wdl", "git_repo"]

    def __init__(self, state: Dict[str, Any] = None, opid: str = None):
        if state is None:
            state = {}
        self.cached_state = state
        if opid and "opid" in self.cached_state:
            raise ValueError("opid already set in job state")
        if opid:
            self.cached_state["opid"] = opid

    def generate_workflow_inputs(self) -> Dict[str, str]:
        """ Generate inputs for the job runner from the workflow state """
        inputs = {}
        prefix = self.input_prefix
        for input_key, input_val in self.inputs.items():
            inputs[f"{prefix}.{input_key}"] = input_val
        return inputs

    def generate_workflow_labels(self) -> Dict[str, str]:
        """ Generate labels for the job runner from the workflow state """
        labels = {param: self.config[param] for param in self.LABEL_PARAMETERS}
        labels["submitter"] = self.LABEL_SUBMITTER_VALUE
        # some Cromwell-specific labels
        labels["pipeline_version"] = self.config["release"]
        labels["pipeline"] = self.config["wdl"]
        labels["activity_id"] = self.workflow_execution_id
        labels["opid"] = self.opid
        return labels

    def generate_submission_files(self, for_jaws: bool = False) -> Dict[str, Any]:
        """ Generate the files needed for a Cromwell job submission """
        files = {}
        try:
            # Get file paths
            wdl_file = self.fetch_release_file(self.config["wdl"], suffix=".wdl")
            bundle_file = self.fetch_release_file("bundle.zip", suffix=".zip")
            workflow_inputs_path = _json_tmp(self.generate_workflow_inputs())
            workflow_labels_path = _json_tmp(self.generate_workflow_labels())

            if for_jaws:
                files = {
                    "wdl_file": wdl_file,
                    "sub": bundle_file,
                    "inputs": workflow_inputs_path,
                }
            else: # open the files for submission
                files = {
                    "workflowSource": open(wdl_file, "rb"),
                    "workflowDependencies": open(bundle_file, "rb"),
                    "workflowInputs": open(workflow_inputs_path, "rb"),
                    "labels": open(workflow_labels_path, "rb"),
                }

            logger.info(f"WDL file: {wdl_file}")
            logger.info(f"Bundle file: {bundle_file}")
            # dump the workflow inputs and labels to the log
            with open(workflow_inputs_path) as f:
                inputs_dump = json.load(f)
                logger.info("Workflow inputs:")
                logger.info(json.dumps(inputs_dump, indent=2))

            with open(workflow_labels_path) as f:
                labels_dump = json.load(f)
                logger.info("Workflow labels:")
                logger.info(json.dumps(labels_dump, indent=2))

        except Exception as e:
            logger.error(f"Failed to generate submission files: {e}")
            _cleanup_files(list(files.values()))
            raise e
        return files

    def update_state(self, state: Dict[str, Any]):
        self.cached_state.update(state)

    @property
    def state(self) -> Dict[str, Any]:
        return self.cached_state

    @property
    def config(self) -> Dict[str, Any]:
        # for backward compatibility we need to check for both keys
        return self.cached_state.get("conf", self.cached_state.get("config", {}))

    @property
    def last_status(self) -> str:
        return self.cached_state.get("last_status", "unknown")

    @last_status.setter
    def last_status(self, status: str):
        self.cached_state["last_status"] = status

    @property
    def failed_count(self) -> int:
        return self.cached_state.get("failed_count", 0)

    @failed_count.setter
    def failed_count(self, count: int):
        self.cached_state["failed_count"] = count

    @property
    def execution_template(self) -> Dict[str, str]:
        # for backward compatibility we need to check for both keys
        return self.config.get("workflow_execution", self.config.get("activity", {}))

    @property
    def workflow_execution_id(self) -> Optional[str]:
        # for backward compatibility we need to check for both keys
        return self.config.get("activity_id", self.config.get("workflow_execution_id", None))

    @property
    def was_informed_by(self) -> Optional[str]:
        return self.config.get("was_informed_by", None)

    @property
    def wdl(self) -> Optional[str]:
        return self.config.get("wdl", None)

    @property
    def release(self) -> Optional[str]:
        return self.config.get("release", None)


    @property
    def workflow_execution_type(self) -> Optional[str]:
        return self.execution_template.get("type", None)

    @property
    def workflow_execution_name(self) -> Optional[str]:
        name_base = self.execution_template.get("name", None)
        if name_base:
            return name_base.replace("{id}", self.workflow_execution_id)
        return None

    @property
    def data_outputs(self) -> List[Dict[str, str]]:
        return self.config.get("outputs", [])

    @property
    def input_prefix(self) -> Optional[str]:
        return self.config.get("input_prefix", None)

    @property
    def inputs(self) -> Dict[str, str]:
        return self.config.get("inputs", {})

    @property
    def nmdc_jobid(self) -> Optional[str]:
        # different keys in state file vs database record
        return self.cached_state.get("nmdc_jobid", self.cached_state.get("id", None))

    @property
    def job_runner_id(self) -> Optional[str]:
        # Cromwell and JAWS job ids
        job_runner_ids = ["cromwell_jobid", "jaws_jobid"]
        for job_runner_id in job_runner_ids:
            if job_runner_id in self.cached_state:
                return self.cached_state[job_runner_id]

    @property
    def opid(self) -> Optional[str]:
        return self.cached_state.get("opid", None)

    @opid.setter
    def opid(self, opid: str):
        if self.opid:
            raise ValueError("opid already set in job state")
        self.cached_state["opid"] = opid

    def fetch_release_file(self, filename: str, suffix: str = None) -> str:
        """
        Download a release file from the Git repository and save it as a temporary file.
        Note: the temporary file is not deleted automatically.
        """
        logger.debug(f"Fetching release file: {filename}")
        url = self._build_release_url(filename)
        logger.debug(f"Fetching release file from URL: {url}")
        # download the file as a stream to handle large files
        response = requests.get(url, stream=True)
        try:
            response.raise_for_status()
            # create a named temporary file
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
                self._write_stream_to_file(response, tmp_file)
                return tmp_file.name
        finally:
            response.close()

    def _build_release_url(self, filename: str) -> str:
        """Build the URL for a release file in the Git repository."""
        logger.debug(f"Building release URL for {filename}")
        release = self.config["release"]
        logger.debug(f"Release: {release}")
        base_url = self.config["git_repo"].rstrip("/")
        url = f"{base_url}{self.GIT_RELEASES_PATH}/{release}/{filename}"
        return url

    def _write_stream_to_file(self, response: requests.Response, file: tempfile.NamedTemporaryFile) -> None:
        """Write a stream from a requests response to a file."""
        try:
            for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                if chunk:
                    file.write(chunk)
            file.flush()
        except Exception as e:
            # clean up the temporary file
            Path(file.name).unlink(missing_ok=True)
            logger.error(f"Error writing stream to file: {e}")
            raise e


class WorkflowJob:
    """
    A class to manage a Workflow's job state and execution, including submission, status, and output. A WorkflowJob
    combines a SiteConfig object, a WorkflowStateManager object, and a JobRunner object to manage the job state and
    execution, and to propagate job results back to the workflow state and ultimately to the database.
    A WorkflowJob object is created with:
    - a SiteConfig object
    - a workflow state dictionary
    - a job metadata dictionary
    - an optional operation id (opid)
    - an optional JobRunnerABC object (default is CromwellRunner)


    """
    def __init__(self, site_config: SiteConfig, workflow_state: Dict[str, Any] = None,
                 job_metadata: Dict['str', Any] = None, opid: str = None, jaws_api: jaws_api.JawsApi = None) -> None:
        self.site_config = site_config
        self.workflow = WorkflowStateManager(workflow_state, opid)
        # Use JawsRunner if jaws_api is provided, otherwise use CromwellRunner
        if jaws_api is None:
            job_runner = CromwellRunner(site_config, self.workflow, job_metadata)
        else:
            job_runner = JawsRunner(site_config, self.workflow, jaws_api, job_metadata)
        self.job = job_runner

    # Properties to access the site config, job state, and job runner attributes
    @property
    def opid(self) -> Optional[str]:
        """ Get the operation id """
        return self.workflow.state.get("opid", None)

    def set_opid(self, opid: str, force: bool = False):
        """ Set the operation id """
        if self.opid and not force:
            raise ValueError("opid already set in job state")
        self.workflow.update_state({"opid": opid})

    @property
    def done(self) -> Optional[bool]:
        """ Get the done state of the job """
        return self.workflow.state.get("done", None)

    @done.setter
    def done(self, done: bool):
        """ Set the done state of the job """
        self.workflow.update_state({"done": done})

    @property
    def job_status(self) -> str:
        """
        Get the status of the job. If the job has not been submitted, return "Unsubmitted".
        If the job has failed and the number of retries has been exceeded, return "Failed".
        Otherwise, return the status from the job runner.
        """
        status = None
        # extend this list as needed for other job runners
        job_id_keys = ["cromwell_jobid", "jaws_jobid"]
        failed_count = self.workflow.state.get("failed_count", 0)
        # if none of the job id keys are in the workflow state, it is unsubmitted
        if not any(key in self.workflow.state for key in job_id_keys):
            status = "Unsubmitted"
            self.workflow.update_state({"last_status": status})
        elif self.workflow.state.get("last_status") == "Succeeded":
            status = "Succeeded"
        elif self.workflow.state.get("last_status") == "Failed" and failed_count >= self.job.max_retries:
            status = "Failed"
        else:
            status = self.job.get_job_status()
            self.workflow.update_state({"last_status": status})
        return status

    @property
    def workflow_execution_id(self) -> Optional[str]:
        """ Get the workflow execution id """
        return self.workflow.workflow_execution_id

    @property
    def data_dir(self) -> str:
        """ Get the data directory """
        return self.site_config.data_dir

    @property
    def execution_resource(self) -> str:
        """ Get the execution resource (e.g., NERSC-Perlmutter) """
        return self.site_config.resource

    @property
    def url_root(self) -> str:
        """ Get the URL root """
        return self.site_config.url_root

    @property
    def was_informed_by(self) -> str:
        """ get the was_informed_by ID value """
        return self.workflow.was_informed_by

    @property
    def as_workflow_execution_dict(self) -> Dict[str, Any]:
        """
        Create a dictionary representation of the basic workflow execution attributes for a WorkflowJob.
        """
        base_dict = {
            "id": self.workflow_execution_id,
            "type": self.workflow.workflow_execution_type,
            "name": self.workflow.workflow_execution_name,
            "git_url": self.workflow.config["git_repo"],
            "execution_resource": self.execution_resource,
            "was_informed_by": self.was_informed_by,
            "has_input": [dobj["id"] for dobj in self.workflow.config["input_data_objects"]],
            "started_at_time": self.job.started_at_time,
            "ended_at_time": self.job.ended_at_time,
            "version": self.workflow.config["release"], }
        return base_dict

    def make_data_objects(self, output_dir: Union[str, Path] = None) -> List[DataObject]:
        """
        Create DataObject objects for each output of the job.
        """

        data_objects = []

        logger.info(f"Creating data objects for job {self.workflow_execution_id}")
        for output_spec in self.workflow.data_outputs:  # specs are defined in the workflow.yaml file under Outputs
            output_key = f"{self.workflow.input_prefix}.{output_spec['output']}"
            # get the full path to the output file from the job_runner
            logger.info(f"Searching job outputs: {self.job.outputs}")
            if output_key not in self.job.outputs:
                logger.warning(f"Output key {output_key} not found in job outputs")
                continue
            output_file = Path(self.job.outputs[output_key])
            logger.info(f"Create Data Object: {output_key} file path: {output_file}")
            if not output_file.exists():
                if output_spec.get("optional"):
                    logger.debug(f"Optional output {output_key} not found in job outputs")
                    continue
                else:
                    logger.warning(f"Required output {output_key} not found in job outputs")
                    continue


            md5_sum = _md5(output_file)
            file_size_bytes = output_file.stat().st_size
            file_url = f"{self.url_root}/{self.was_informed_by}/{self.workflow_execution_id}/{output_file.name}"

            if output_dir:
                new_output_file_path = Path(output_dir) / output_file.name
                # copy the file to the output directory
                shutil.copy(output_file, new_output_file_path)

                # Check that the file was completely copied by md5 value. If not, try one more time.
                # If it still fails, raise an exception.
                if md5_sum != _md5(new_output_file_path):
                    shutil.copy(output_file, new_output_file_path)
                    if md5_sum != _md5(new_output_file_path):
                        raise IOError(f"Failed to copy {output_file} to {new_output_file_path}")

            else:
                logger.warning(f"Output directory not provided, not copying {output_file} to output directory")

            # create a DataObject object
            data_object = DataObject (
                id=output_spec["id"], 
                name=output_file.name, 
                type="nmdc:DataObject", 
                url=file_url,
                data_object_type=output_spec["data_object_type"], 
                md5_checksum=md5_sum,
                file_size_bytes=file_size_bytes,
                description=output_spec["description"].replace('{id}', self.workflow_execution_id),
                was_generated_by=self.workflow_execution_id, 
                data_category=DataCategoryEnum.processed_data
            )

            data_objects.append(data_object)
            
        return data_objects

    def make_workflow_execution(self, data_objects: List[DataObject]) -> WorkflowExecution:
        """
        Create a workflow execution instance for the job. This record includes the basic workflow execution attributes
        and the data objects generated by the job. Additional workflow-specific attributes can be defined in the
        workflow execution template and read from a job's output files.
        The data objects are added to the record as a list of IDs in the "has_output" key.
        """
        wf_dict = self.as_workflow_execution_dict
        wf_dict["has_output"] = [dobj.id for dobj in data_objects]

        # workflow-specific keys
        logical_names = set()
        field_names = set()
        pattern = r'\{outputs\.(\w+)\.(\w+)\}'
        for attr_key, attr_val in self.workflow.execution_template.items():
            if attr_val.startswith("{outputs."):
                match = re.match(pattern, attr_val)
                if not match:
                    logger.warning(f"Invalid output reference {attr_val}")
                    continue
                logical_names.add(match.group(1))
                field_names.add(match.group(2))

        for logical_name in logical_names:
            output_key = f"{self.workflow.input_prefix}.{logical_name}"
            data_path = self.job.outputs.get(output_key)
            if data_path:
                # read in as json
                with open(data_path) as f:
                    data = json.load(f)
                for field_name in field_names:
                    # add to wf_dict if it has a value
                    if field_name in data:
                        wf_dict[field_name] = data[field_name]
                    else:
                        logger.warning(f"Field {field_name} not found in {data_path}")

        wfe = workflow_process_factory(wf_dict)
        return wfe

    def generate_job_inputs(self) -> Dict[str, str]:
        """
        Generate the inputs for a job from the workflow state.
        """
        inputs = {}
        prefix = self.workflow.input_prefix
        for input_key, input_val in self.workflow.inputs.items():
            # special case for resource
            if input_val == "{resource}":
                input_val = self.site_config.resource
            inputs[f"{prefix}.{input_key}"] = input_val
        return inputs



def _json_tmp(data):
    fp, fname = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fp, "w") as fd:
        fd.write(json.dumps(data))
    return fname


def _md5(file):
    return hashlib.md5(open(file, "rb").read()).hexdigest()


def _cleanup_files(files: List[Union[tempfile.NamedTemporaryFile, tempfile.SpooledTemporaryFile]]):
    """Safely closes and removes files."""
    for file in files:
        try:
            file.close()
            os.unlink(file.name)
        except Exception as e:
            logger.error(f"Failed to cleanup file: {e}")

def _cleanup_dirs(dir_paths: list[str | Path]):
    for path in dir_paths:
        try:
            shutil.rmtree(path)
        except Exception as e:
            logger.error(f"Error removing directory {path}: {e}")