import logging
import asyncio
from datetime import datetime
from typing import List, Dict
import uuid
import os
from time import sleep as _sleep
from nmdc_automation.api.nmdcapi import NmdcRuntimeApi
#from nmdc_automation.db.nmdc_mongo import get_db
from nmdc_automation.workflow_automation.workflows import load_workflow_configs
from functools import lru_cache
from nmdc_automation.workflow_automation.workflow_process import load_workflow_process_nodes
from nmdc_automation.models.workflow import WorkflowConfig, WorkflowProcessNode
from semver.version import Version
import sys


_POLL_INTERVAL = 60
_WF_YAML_ENV = "NMDC_WORKFLOW_YAML_FILE"


# configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def within_range(wf1: WorkflowConfig, wf2: WorkflowConfig, force=False) -> bool:
    """
    Determine if two workflows are within a major and minor
    version of each other.
    """

    def get_version(wf):
        v_string = wf.version.lstrip("b").lstrip("v")
        return Version.parse(v_string)

    # Apples and oranges
    if wf1.name != wf2.name:
        return False
    v1 = get_version(wf1)
    v2 = get_version(wf2)
    if force:
        return v1 == v2
    if v1.major == v2.major and v1.minor == v2.minor:
        return True
    return False


class SchedulerJob:
    """
    Class to hold information for new jobs
    """

    def __init__(self, workflow: WorkflowConfig, trigger_act: WorkflowProcessNode, manifest_map: Dict[str, List[str]]):
        """
        Initializes a SchedulerJob with a trigger and conditionally sets its
        informed_by attribute based on the trigger's manifest.

        Args:
            workflow: The workflow configuration.
            trigger_act: The WorkflowProcessingNode that triggered the job.
            manifest_id_map: A dictionary mapping manifest values to data generations IDs
                             to create informed_by lists.
        """
        self.workflow = workflow
        self.trigger_act = trigger_act
        self.trigger_id = trigger_act.id
        self.informed_by = trigger_act.was_informed_by

        # Default has no manifest 
        self.manifest = None
        
        # Set the manifest if found; DataGeneration workflowprocess nodes need their
        # was_informed_by list assigned from the manifest_map
        # Note: was_informed_by will be properly set from trigger_act.was_informed_by 
        # for jobs downstream of readsqc (non-dgns wf records)
        
        if len(trigger_act.manifest) == 1:

            manifest_key = trigger_act.manifest[0]

            # Save it to the class
            self.manifest = manifest_key

            # Use .get() to safely retrieve the mapped value.
            # It will return None if the key doesn't exist.
            mapped_value = manifest_map.get(manifest_key)
            
            # For dgns wfp nodes
            # Check if a value was found, is a dict, and contains the required key.
            # This will be the associated data_generation_set IDs with the manifest set
            if isinstance(mapped_value, dict) and 'data_generation_set' in mapped_value:
                if self.trigger_id in mapped_value['data_generation_set']:
                    self.informed_by = mapped_value['data_generation_set']

        
                


class MissingDataObjectException(Exception):
    """ Custom exception for missing data objects"""
    pass


class Scheduler:

    #def __init__(self, db, workflow_yaml,
    #             site_conf="site_configuration.toml"):
    def __init__(self, workflow_yaml,
                 site_conf="site_configuration.toml", api=None):

        # Init
        # wf_file = os.environ.get(_WF_YAML_ENV, wfn)
        self.workflows = load_workflow_configs(workflow_yaml)
        #self.db = db
        
        # Updated to handle passed in api (for example test fixture), else initialize like usual
        if api:
            self.api = api
        else:
            self.api = NmdcRuntimeApi(site_conf)
            
        # TODO: Make force a optional parameter
        self.force = False
        if os.environ.get("FORCE") == "1":
            logger.info("Setting force on")
            self.force = True
        self._messages = []

    async def run(self):
        logger.info("Starting Scheduler")
        while True:
            self.cycle()
            await asyncio.sleep(_POLL_INTERVAL)

    def create_job_rec(self, job: SchedulerJob, manifest_map: Dict[str, List[str]]):
        """
        This takes a job and using the workflow definition,
        resolves all the information needed to create a
        job record.
        """
        # Get all the data objects
        next_act = job.trigger_act
        do_by_type = dict()
        while next_act:

            #
            # If manifest is not empty, then this is a data generation stored in the WorkflowProcessNode
            # Note: Currently only support one manifest per workflowprocessnode/datagen
            #
            if len(next_act.manifest) == 1 and job.trigger_id in manifest_map[next_act.manifest[0]]['data_generation_set']:

                # Find the data objects associated with the manifest using manifest_map
                for data_object in manifest_map[next_act.manifest[0]]['data_object_set']:
                    do_type = data_object.data_object_type_text
                    if do_type not in do_by_type:    
                        do_by_type[do_type] = []
                    do_by_type[do_type].append(data_object)

            else:
                for do_type, data_object in next_act.data_objects_by_type.items():
                    if do_type in do_by_type:
                        logger.debug(f"Ignoring Duplicate type: {do_type} {data_object.id} {next_act.id}")
                        continue
                    do_by_type[do_type] = []
                    do_by_type[do_type].append(data_object)
                    #do_by_type[do_type] = data_object #used to be scalar
            
            # do_by_type.update(next_act.data_objects_by_type.__dict__)
            next_act = next_act.parent

        wf = job.workflow
        base_id, iteration = self.get_activity_id(wf, job.informed_by)
        workflow_execution_id = f"{base_id}.{iteration}"
        input_data_objects = []
        inputs = dict()
        optional_inputs = wf.optional_inputs
        for k, v in job.workflow.inputs.items():
            # some inputs are booleans and should not be modified
            if isinstance(v, bool):
                inputs[k] = v
                continue
            elif v.startswith("do:"):
                do_type = v[3:]
                dobj_list = do_by_type.get(do_type)
                if not dobj_list:
                    if k in optional_inputs:
                        continue
                    raise MissingDataObjectException(f"Unable to find {do_type} in {do_by_type}")
                if len(dobj_list) == 1:
                    input_data_objects.append(dobj_list[0].as_dict())
                
                    if k == "input_files":
                        v = [dobj_list[0]["url"]]
                    elif k in ["input_fastq1", "input_fastq2"]:  
                        v = [dobj_list[0]["url"]]
                    else:
                        v = dobj_list[0]["url"]
                
                # For multi-input, it goes here to produce []
                else:
                    v = []
                    for dobj in dobj_list:
                        input_data_objects.append(dobj.as_dict())
    
                        v.append(dobj["url"])
                        
                    
            # TODO: Make this smarter
            elif v == "{was_informed_by}":
                v = job.informed_by  #Check that this works for 1 or >1 todojp 20250911
            elif v == "{workflow_execution_id}":
                v = workflow_execution_id
            elif v == "{predecessor_activity_id}":
                v = job.trigger_act.id

            inputs[k] = v

        # Build the respoonse
        job_config = {
            "git_repo": wf.git_repo,
            "release": wf.version,
            "wdl": wf.wdl,
            "activity_id": workflow_execution_id,
            "activity_set": wf.collection,
            "was_informed_by": job.informed_by,
            "trigger_activity": job.trigger_id,
            "iteration": iteration,
            "input_prefix": wf.input_prefix,
            "inputs": inputs,
            "input_data_objects": input_data_objects,
        }
        if wf.workflow_execution:
            job_config["activity"] = wf.workflow_execution
        if wf.outputs:
            outputs = []
            for output in wf.outputs:
                # Mint an ID
                # Note - the minter uses the informed_by to generate a metadata record so no need
                # to check for the length of the array.
                output["id"] = self.api.minter("nmdc:DataObject", job.informed_by)
                outputs.append(output)
            job_config["outputs"] = outputs
        
        # Save the associated manifest to the job config
        if job.manifest:
            job_config["manifest"] = job.manifest

        jr = {
            "workflow": {"id": f"{wf.name}: {wf.version}"},
            #"id": self.generate_job_id(),
            #"created_at": datetime.today().replace(microsecond=0),
            "config": job_config,
            "claims": [],
        }

        #logger.info(f'JOB RECORD: {jr["id"]}')
        # This would make the job record
        # print(json.dumps(ji, indent=2))
        return jr

    def generate_job_id(self) -> str:
        """
        Generate an ID for the job

        Note: This is not currently Napa compliant.  Since these are somewhat
        ephemeral I'm not sure if it matters though.
        """
        u = str(uuid.uuid1())
        return f"nmdc:{u}"

    def mock_mint(self, id_type):  # pragma: no cover
        """
        Return a fixed pattern used for testing
        """
        mapping = {
            "nmdc:ReadQcAnalysisActivity": "mgrqc",
            "nmdc:MetagenomeAssembly": "mgasm",
            "nmdc:MetagenomeAnnotationActivity": "mgann",
            "nmdc:MAGsAnalysisActivity": "mgmag",
            "nmdc:ReadBasedTaxonomyAnalysisActivity": "mgrbt",
        }
        return f"nmdc:wf{mapping[id_type]}-11-xxxxxx"

    def get_activity_id(self, wf: WorkflowConfig, informed_by: list[str]):
        """
        See if anything exist for this and if not
        mint a new id.
        """
        # We need to see if any version exist and
        # if so get its ID
        ct = 0
        last_id = None
        
        # Only look for ID for informed_by len=1, and handle multi later -jlp 20250722
        # This should be ok to pass the array of was_informed_by to find the workflow in mongo -jlp 20250828
        #if len(informed_by) == 1:
        q = {"was_informed_by": informed_by, "type": wf.type}
        #for doc in self.db[wf.collection].find(q):
        for doc in self.api.list_from_collection(wf.collection, q, "id"):
            ct += 1
            last_id = doc["id"]


        if ct == 0 or last_id is None:
            # Get an ID
            if os.environ.get("MOCK_MINT"):
                root_id = self.mock_mint(wf.type)
            else:
                root_id = self.api.minter(wf.type, informed_by)
            return root_id, 1
        else:
            root_id = ".".join(last_id.split(".")[0:-1])
            return root_id, ct + 1

    @lru_cache(maxsize=128)
    def get_existing_jobs(self, wf: WorkflowConfig):
        """
        Get the existing jobs for a workflow, including cancelled jobs
        """
        existing_jobs = set()
        # Filter by git_repo and version
        # Find all existing jobs for this workflow
        q = {"config.git_repo": wf.git_repo, "config.release": wf.version}
        #for j in self.db.jobs.find(q):
        for j in self.api.list_jobs(q):
            # the assumption is that a job in any state has been triggered by an activity
            # that was the result of an existing (completed) job
            act = j["config"]["trigger_activity"]
            existing_jobs.add(act)
        return existing_jobs

    def find_new_jobs(self, wfp_node: WorkflowProcessNode, manifest_map: Dict[str, List[str]], all_jobs: List[SchedulerJob]) -> List[SchedulerJob]:
        """
        Find new jobs for a workflow process node. A new job:
        - Is either not in the Jobs collection or is cancelled
        - Is not satisfied by an existing version of a workflow execution
        - Is for a workflow that is enabled
        """
        new_jobs = []
        # Loop over the derived workflows for this
        # activities' workflow
        for wf in wfp_node.workflow.children:
            # Ignore disabled workflows
            if not wf.enabled:
                msg = f"Skipping disabled workflow {wf.name}:{wf.version}"
                if msg not in self._messages:
                    logger.info(msg)
                    self._messages.append(msg)
                continue
            # See if we already have a job for this
            if wfp_node.id in self.get_existing_jobs(wf):
                msg = f"Skipping existing job for {wfp_node.id} {wf.name}:{wf.version}"
                if msg not in self._messages:
                    logger.info(msg)
                    self._messages.append(msg)
                continue
            
            #
            # This check is only for wfp_nodes that are data_generation_set records to avoid duplicate scheduling
            # 
            # If current wfp_node.id is not in existing jobs, see if this has a manifest record,
            # then check for other associated data generation records jobs that exist for this wf
            found_existing_manifest_job = False
            associated_wfp_node_id = None
            if len(wfp_node.manifest) == 1:
                if wfp_node.id in manifest_map[wfp_node.manifest[0]]['data_generation_set']:

                    for dgns_id in manifest_map[wfp_node.manifest[0]]['data_generation_set']:
                        # Only need to check for others dgns since already checked itself above
                        if dgns_id != wfp_node.id:
                            if dgns_id in self.get_existing_jobs(wf):
                                found_existing_manifest_job = True
                                associated_wfp_node_id = dgns_id
                                break
                    
                    # If not found, also check if it was just added to list of all jobs 
                    if not found_existing_manifest_job:
                        for new_job in all_jobs:
                            if new_job.manifest:
                                if new_job.manifest == wfp_node.manifest[0]:
                                    if new_job.workflow.name == wf.name:
                                        found_existing_manifest_job = True
                                        associated_wfp_node_id = new_job.trigger_id
                                        break


                    if found_existing_manifest_job:
                        msg = f"Skipping existing job due to associated data generation record {associated_wfp_node_id} for {wfp_node.id} {wf.name}:{wf.version}"
                        if msg not in self._messages:
                            logger.info(msg)
                            self._messages.append(msg)
                        continue


                


            # Look at previously generated derived
            # activities to see if this is already done.
            # Note: this looks to be comparing the latest workflow for this analysis type set under
            # the workflow process node (instead of the actual version set) vs the expected workflow type
            # but this isn't currently impacting what should be the right answer so maybe this is leftover from 
            # the refactor but making a note of it. -jlp 20250714
            for child_act in wfp_node.children:
                if within_range(child_act.workflow, wf, force=self.force):
                    msg = f"Skipping existing job for {child_act.id} {wf.name}:{wf.version}"
                    if msg not in self._messages:
                        logger.info(msg)
                        self._messages.append(msg)
                    break
            else:
                # These means no existing activities were
                # found that matched this workflow, so we
                # add a job
                msg = f"Creating a job {wf.name}:{wf.version} for {wfp_node.process.id}"
                if msg not in self._messages:
                    logger.info(msg)
                    self._messages.append(msg)
                new_jobs.append(SchedulerJob(wf, wfp_node, manifest_map))

        return new_jobs

    def cycle(self, dryrun: bool = False, skiplist: list[str] = None,
              allowlist=None) -> list:
        """
        This function does a single cycle of looking for new jobs
        """
        #wfp_nodes = load_workflow_process_nodes(self.db, self.workflows, allowlist) #orig
        #wfp_nodes = load_workflow_process_nodes(self.api, self.workflows, allowlist) #605
        wfp_nodes, manifest_map = load_workflow_process_nodes(self.api, self.workflows, allowlist)
        if wfp_nodes:
            for wfp_node in wfp_nodes:
                msg = f"Found workflow process node {wfp_node.id}"
                if msg not in self._messages:
                    logger.info(msg)
                    self._messages.append(msg)
        else:
            msg = f"No workflow process nodes found for {allowlist}"
            if msg not in self._messages:
                logger.info(msg)
                self._messages.append(msg)

        self.get_existing_jobs.cache_clear()
        job_recs = []
        all_jobs = []

        for wfp_node in wfp_nodes:
            if skiplist and wfp_node.id in skiplist:
                continue
            if not wfp_node.workflow.enabled:
                continue
            jobs = self.find_new_jobs(wfp_node, manifest_map, all_jobs)
            all_jobs.extend(jobs)

            if jobs:
                logger.info(f"Found {len(jobs)} new jobs for {wfp_node.id}")
            for job in jobs:
                msg = f"new job: informed_by: {job.informed_by} trigger: {job.trigger_id} "
                msg += f"wf: {job.workflow.name} ver: {job.workflow.version}"
                logger.info(msg)

                if dryrun:
                    continue
                try:
                    # This jr does not have the ID until it is submitted to mongo
                    jr = self.create_job_rec(job, manifest_map)
                    
                    #self.db.jobs.insert_one(jr) #TODO replace this with create_job endpoint below
                    complete_jr = self.api.create_job(jr)

                    if complete_jr:
                        logger.info(f'JOB RECORD: {complete_jr["id"]}')
                        job_recs.append(complete_jr)
                        
                except MissingDataObjectException as e:
                    logger.warning(f"Caught missing Data Object(s) for {job.informed_by}: Skipping")
                    logger.warning(e)
                    continue
                except Exception as e:
                    logger.exception(e)
                    raise
        return job_recs



def main(site_conf, wf_file):  # pragma: no cover
    """
    Main function
    """
    # site_conf = os.environ.get("NMDC_SITE_CONF", "site_configuration.toml")
    #db = get_db()
    logger.info("Initializing Scheduler")
    #sched = Scheduler(db, wf_file, site_conf=site_conf)
    sched = Scheduler(wf_file, site_conf=site_conf)

    dryrun = False
    if os.environ.get("DRYRUN") == "1":
        dryrun = True
    skiplist = set()
    allowlist = None
    if os.environ.get("SKIPLISTFILE"):
        with open(os.environ.get("SKIPLISTFILE")) as f:
            for line in f:
                skiplist.add(line.rstrip())

    logger.info("Reading Allowlist")
    if os.environ.get("ALLOWLISTFILE"):
        allowlist = set()
        with open(os.environ.get("ALLOWLISTFILE")) as f:
            for line in f:
                allowlist.add(line.rstrip())
        logger.info(f"Read {len(allowlist)} items")
        for item in allowlist:
            logger.info(f"Allowing: {item}")

    logger.info("Starting Scheduler")
    cycle_count = 0
    while True:
        sched.cycle(dryrun=dryrun, skiplist=skiplist, allowlist=allowlist)
        cycle_count += 1
        if dryrun:
            break
        _sleep(_POLL_INTERVAL)
        if cycle_count % 100 == 0:
            logger.info(f"Cycles: {cycle_count}")


if __name__ == "__main__":  # pragma: no cover
    # site_conf and wf_file are passed in as arguments
    main(site_conf=sys.argv[1], wf_file=sys.argv[2])
