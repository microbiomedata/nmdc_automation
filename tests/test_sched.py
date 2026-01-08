from nmdc_automation.workflow_automation.sched import Scheduler, SchedulerJob, MissingDataObjectException
from pytest import mark
import pytest
from unittest.mock import patch, MagicMock

from nmdc_automation.workflow_automation.workflow_process import load_workflow_process_nodes
from nmdc_automation.workflow_automation.workflows import load_workflow_configs
from tests.fixtures.db_utils import init_test, load_fixture, read_json, reset_db
from unittest.mock import patch, PropertyMock, Mock
from nmdc_automation.api.nmdcapi import NmdcRuntimeApi

from pathlib import Path

@mark.parametrize("workflow_file", [
    "workflows.yaml",
    "workflows-mt.yaml"
])

#def test_scheduler_cycle(test_db, mock_api, workflow_file, workflows_config_dir, site_config_file):
def test_scheduler_cycle(test_db, test_client, workflow_file, workflows_config_dir, site_config_file):
    """
    Test basic job creation.
    """
    exp_rqc_git_repos = [
        "https://github.com/microbiomedata/ReadsQC",
        "https://github.com/microbiomedata/metaT_ReadsQC"
    ]
    # init_test(test_db)
    reset_db(test_db)

    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")

    # Scheduler will find one job to create
    exp_num_jobs_initial = 1
    exp_num_jobs_cycle_1 = 0
    #jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / workflow_file,
    #               site_conf=site_config_file)
    jm = Scheduler(workflow_yaml=workflows_config_dir / workflow_file,
                   site_conf=site_config_file, api=test_client)
    resp = jm.cycle()
    assert len(resp) == exp_num_jobs_initial
    assert resp[0]["config"]["git_repo"] in exp_rqc_git_repos

    # All jobs should now be in a submitted state
    resp = jm.cycle()
    assert len(resp) == exp_num_jobs_cycle_1

@mark.parametrize("workflow_file", [
    "workflows.yaml",
    "workflows-mt.yaml"
])
#def test_progress(test_db, mock_api, workflow_file, workflows_config_dir, site_config_file):
def test_progress(test_db, test_client, workflow_file, workflows_config_dir, site_config_file):
    reset_db(test_db)
    metatranscriptome = False
    if workflow_file == "workflows-mt.yaml":
        metatranscriptome = True
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")



    #jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / workflow_file,
    #               site_conf= site_config_file)
    jm = Scheduler(workflow_yaml=workflows_config_dir / workflow_file,
                   site_conf= site_config_file,
                   api=test_client)
    workflow_by_name = dict()
    for wf in jm.workflows:
        workflow_by_name[wf.name] = wf

    # There should be 1 RQC job for each omics_processing_set record
    resp = jm.cycle()
    assert len(resp) == 1

    # We simulate the RQC job finishing
    load_fixture(test_db, "read_qc_analysis.json", col="workflow_execution_set")

    resp = jm.cycle()
    if metatranscriptome:
        # assembly
        exp_num_post_rqc_jobs = 1
        exp_num_post_annotation_jobs = 1
    else:
        # assembly, rba
        exp_num_post_rqc_jobs = 2
        exp_num_post_annotation_jobs = 2

        # Get the assembly job record from resp and check the inputs
        asm_job = [j for j in resp if j["config"]["activity"]["type"] == "nmdc:MetagenomeAssembly"][0]
        assert "shortRead" in asm_job["config"]["inputs"]
        assert isinstance(asm_job["config"]["inputs"]["shortRead"], bool)

    assert len(resp) == exp_num_post_rqc_jobs

    if metatranscriptome:
        # simulate assembly job finishing
        load_fixture(test_db, "metatranscriptome_assembly.json", col="workflow_execution_set")
        # We should see a metatranscriptome annotation job
        resp = jm.cycle()
        assert len(resp) == 1
        assert resp[0]["config"]["activity"]["type"] == "nmdc:MetatranscriptomeAnnotation"

        resp = jm.cycle()
        # all jobs should be in a submitted state
        assert len(resp) == 0

        # simulate annotation job finishing
        load_fixture(test_db, "metatranscriptome_annotation.json", col="workflow_execution_set")
        resp = jm.cycle()
        assert len(resp) == 1
        assert resp[0]["config"]["activity"]["type"] == "nmdc:MetatranscriptomeExpressionAnalysis"
    else:
        # simulate assembly job finishing
        load_fixture(test_db, "metagenome_assembly.json", col="workflow_execution_set")
        # We should see a metagenome annotation job
        resp = jm.cycle()
        assert len(resp) == 1
        assert resp[0]["config"]["activity"]["type"] == "nmdc:MetagenomeAnnotation"

        resp = jm.cycle()
        # all jobs should be in a submitted state
        assert len(resp) == 0

        # simulate annotation job finishing
        load_fixture(test_db, "metagenome_annotation.json", col="workflow_execution_set")
        resp = jm.cycle()
        assert len(resp) == 1
        assert resp[0]["config"]["activity"]["type"] == "nmdc:MagsAnalysis"

    resp = jm.cycle()
    # all jobs should be in a submitted state
    assert len(resp) == 0

    # Let's remove the job records.
    test_db.jobs.delete_many({})
    resp = jm.cycle()
    assert len(resp) == exp_num_post_annotation_jobs


#def test_multiple_versions(test_db, mock_api, workflows_config_dir, site_config_file):
def test_multiple_versions(test_db, test_client, workflows_config_dir, site_config_file):
    init_test(test_db)
    reset_db(test_db)
    test_db.jobs.delete_many({})

    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")

    #jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml",
    #               site_conf=site_config_file)
    jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file,
                   api=test_client)
    workflow_by_name = dict()
    for wf in jm.workflows:
        workflow_by_name[wf.name] = wf

    resp = jm.cycle()
    assert len(resp) == 1
    #

    # We simulate one of the jobs finishing
    load_fixture(test_db, "read_qc_analysis.json", col="workflow_execution_set")
    resp = jm.cycle()
    # We should see one asm and one rba job
    assert len(resp) == 2
    resp = jm.cycle()
    assert len(resp) == 0
    # Simulate the assembly job finishing with an older version
    load_fixture(test_db, "metagenome_assembly.json", col="workflow_execution_set", version="v1.0.2")

    resp = jm.cycle()
    # We should see one rba job
    assert len(resp) == 1
    resp = jm.cycle()
    assert len(resp) == 0


#def test_out_of_range(test_db, mock_api, workflows_config_dir, site_config_file):
def test_out_of_range(test_db, test_client, workflows_config_dir, site_config_file):
    init_test(test_db)
    reset_db(test_db)
    test_db.jobs.delete_many({})
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")
    #jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml",
    #               site_conf=site_config_file)
    jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file,
                   api=test_client)
    # Let's create two RQC records.  One will be in range
    # and the other will not.  We should only get new jobs
    # for the one in range.
    load_fixture(test_db, "read_qc_analysis.json", col="workflow_execution_set")
    load_fixture(test_db, "rqc_out_of_range.json", col="workflow_execution_set")

    resp = jm.cycle()
    # there is one additional metatranscriptome rqc job from the fixture
    assert len(resp) == 2
    resp = jm.cycle()
    assert len(resp) == 0

#def test_type_resolving(test_db, mock_api, workflows_config_dir, site_config_file):
def test_type_resolving(test_db, test_client, workflows_config_dir, site_config_file):
    """
    This tests the handling when the same type is used for
    different activity types.  The desired behavior is to
    use the first match.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")
    load_fixture(test_db, "read_qc_analysis.json", col="workflow_execution_set")

    #jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml",
    #               site_conf=site_config_file)
    jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file,
                   api=test_client)
    workflow_by_name = dict()
    for wf in jm.workflows:
        workflow_by_name[wf.name] = wf

    # mock progress
    load_fixture(test_db, "metagenome_assembly.json", col="workflow_execution_set")
    load_fixture(test_db, "metagenome_annotation.json", col="workflow_execution_set")

    resp = jm.cycle()

    assert len(resp) == 2
    # assert 'annotation' in resp[1]['config']['inputs']['contig_file']

# Not really sure if this is doing what the function name says -jp20251023
@mark.parametrize("workflow_file", [
    "workflows.yaml",
    "workflows-mt.yaml"
])
#def test_scheduler_add_job_rec(test_db, mock_api, workflow_file, workflows_config_dir, site_config_file):
def test_scheduler_add_job_rec(test_db, workflow_file, workflows_config_dir, site_config_file):
    """
    Test basic job creation.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")

    #jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / workflow_file,
    #               site_conf=site_config_file)
    jm = Scheduler(workflow_yaml=workflows_config_dir / workflow_file,
                   site_conf=site_config_file)
    # sanity check
    assert jm


#def test_scheduler_find_new_jobs(test_db, mock_api, workflows_config_dir, site_config_file):
def test_scheduler_find_new_jobs(test_db, test_client, workflows_config_dir, site_config_file):
    """
    Test finding new jobs for a realisitic scenario:
    nmdc:omprc-11-cegmwy02 has no version-current MAGsAnalysis results.  The scheduler should find
    a new job for this.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_objects_2.json", "data_object_set")
    load_fixture(test_db, "data_generation_2.json", "data_generation_set")
    load_fixture(test_db, "workflow_execution_2.json", "workflow_execution_set")

    workflow_config = load_workflow_configs(workflows_config_dir / "workflows.yaml")

    #scheduler = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file)
    scheduler = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml", 
                          site_conf=site_config_file, 
                          api=test_client)
    assert scheduler

    workflow_process_nodes, manifest_map = load_workflow_process_nodes(scheduler.api, workflow_config)
    # sanity check
    assert workflow_process_nodes

    

    new_jobs = []
    found_jobs = []
    for node in workflow_process_nodes:
        found_jobs = scheduler.find_new_jobs(node, manifest_map, new_jobs)
        new_jobs.extend(found_jobs)
    assert new_jobs
    assert len(new_jobs) == 1
    new_job = new_jobs[0]
    assert isinstance(new_job, SchedulerJob)
    assert new_job.workflow.type == "nmdc:MagsAnalysis"
    assert new_job.trigger_act.type == "nmdc:MetagenomeAnnotation"
    assert new_job.trigger_act.data_objects_by_type

    job_req = scheduler.create_job_rec(new_job, manifest_map)
    assert job_req
    assert job_req["config"]["activity"]["type"] == "nmdc:MagsAnalysis"
    assert job_req["config"]["was_informed_by"] == ["nmdc:omprc-11-cegmwy02"]
    assert job_req["config"]["input_data_objects"]


#def test_scheduler_create_job_rec_raises_missing_data_object_exception(test_db, mock_api, workflows_config_dir, site_config_file):
def test_scheduler_create_job_rec_raises_missing_data_object_exception(test_db, test_client, workflows_config_dir, site_config_file):
    """
    Test that create_job_rec raises a MissingDataObjectException for missing data files
    """
    reset_db(test_db)
    load_fixture(test_db, "data_objects_2.json", "data_object_set")
    load_fixture(test_db, "data_generation_2.json", "data_generation_set")
    load_fixture(test_db, "workflow_execution_2.json", "workflow_execution_set")

    workflow_config = load_workflow_configs(workflows_config_dir / "workflows.yaml")

    #scheduler = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file)
    scheduler = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file, api=test_client)
    assert scheduler

    workflow_process_nodes, manifest_map = load_workflow_process_nodes(scheduler.api, workflow_config)
    # sanity check
    assert workflow_process_nodes

    

    new_jobs = []
    found_jobs = []
    for node in workflow_process_nodes:
        found_jobs = scheduler.find_new_jobs(node, manifest_map, new_jobs)
        new_jobs.extend(found_jobs)

    assert new_jobs
    assert len(new_jobs) == 1
    new_job = new_jobs[0]
    assert isinstance(new_job, SchedulerJob)
    assert new_job.workflow.type == "nmdc:MagsAnalysis"
    assert new_job.trigger_act.type == "nmdc:MetagenomeAnnotation"
    assert new_job.trigger_act.data_objects_by_type
    # remove contig file data object
    del new_job.trigger_act.data_objects_by_type["Assembly Contigs"]
    parent = new_job.trigger_act.parent
    del parent.data_objects_by_type["Assembly Contigs"]

    with pytest.raises(MissingDataObjectException):
        job_req = scheduler.create_job_rec(new_job, manifest_map)


#def test_scheduler_create_job_rec_has_input_files_as_array(test_db, mock_api, workflows_config_dir, site_config_file):
def test_scheduler_create_job_rec_has_input_files_as_array(test_db, test_client, workflows_config_dir, site_config_file):
    """
    Test that the input_data_objects field is an array of strings.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")
    load_fixture(test_db, "read_qc_analysis.json", col="workflow_execution_set")

    #jm = Scheduler(
    #    test_db, workflow_yaml=workflows_config_dir / "workflows.yaml",
    #    site_conf=site_config_file
    #    )
    jm = Scheduler(
        workflow_yaml=workflows_config_dir / "workflows.yaml",
        site_conf=site_config_file, 
        api=test_client
        )

    resp = jm.cycle()
    assemblies = [j for j in resp if j["config"]["activity"]["type"] == "nmdc:MetagenomeAssembly"]
    assert assemblies
    assembly = assemblies[0]

    assert isinstance(assembly["config"]["inputs"]["shortRead"], bool)
    assert assembly["config"]["inputs"]["shortRead"] == True
    assert isinstance(assembly["config"]["inputs"]["input_files"], list)


@pytest.mark.parametrize("job_fixture", [
    "job_req_2.json",
    "cancelled_job_req_2.json"
])
def test_scheduler_find_new_jobs_with_existing_job(job_fixture, test_db, test_client, workflows_config_dir, site_config_file):
    """
    Test that the find_new_jobs method works as expected. We load an existing job fixture so we expect no new jobs to be found.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_objects_2.json", "data_object_set")
    load_fixture(test_db, "data_generation_2.json", "data_generation_set")
    load_fixture(test_db, "workflow_execution_2.json", "workflow_execution_set")
    load_fixture(test_db, job_fixture, "jobs")

    workflow_config = load_workflow_configs(workflows_config_dir / "workflows.yaml")

    #scheduler = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file)
    scheduler = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file, api=test_client)
    assert scheduler

    workflow_process_nodes, manifest_map = load_workflow_process_nodes(scheduler.api, workflow_config)
    # sanity check
    assert workflow_process_nodes

    

    new_jobs = []
    found_jobs = []
    for node in workflow_process_nodes:
        found_jobs = scheduler.find_new_jobs(node, manifest_map, new_jobs)
        new_jobs.extend(found_jobs)

    assert not new_jobs

#def test_scheduler_find_new_jobs3(test_db, mock_api, workflows_config_dir, site_config_file):
def test_scheduler_find_new_jobs3(test_db, test_client, workflows_config_dir, site_config_file):
    """
    Test finding new jobs where two annotations with versions within range exist. A new MAGsAnalysis
     should be scheduled only for the latest version (a current bug schedules for both 20250714).
    nmdc:omprc-11-bm72c549The scheduler should find one new job for this.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_objects_3.json", "data_object_set")
    load_fixture(test_db, "data_generation_3.json", "data_generation_set")
    load_fixture(test_db, "workflow_execution_3.json", "workflow_execution_set")

    workflow_config = load_workflow_configs(workflows_config_dir / "workflows.yaml")

    #scheduler = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file)
    scheduler = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file, api=test_client)
    assert scheduler

    workflow_process_nodes, manifest_map = load_workflow_process_nodes(scheduler.api, workflow_config)
    # sanity check
    assert workflow_process_nodes

    

    new_jobs = []
    found_jobs = []
    for node in workflow_process_nodes:
        found_jobs = scheduler.find_new_jobs(node, manifest_map, new_jobs)
        new_jobs.extend(found_jobs)

    assert new_jobs
    assert len(new_jobs) == 1
    new_job = new_jobs[0]
    assert isinstance(new_job, SchedulerJob)
    assert new_job.workflow.type == "nmdc:MagsAnalysis"
    assert new_job.trigger_act.type == "nmdc:MetagenomeAnnotation"
    assert new_job.trigger_act.data_objects_by_type

    job_req = scheduler.create_job_rec(new_job, manifest_map)
    assert job_req
    
    #new_job = new_jobs[1]
    #job_req = scheduler.create_job_rec(new_job, manifest_map)
    #assert job_req

    assert job_req["config"]["activity"]["type"] == "nmdc:MagsAnalysis"
    assert job_req["config"]["was_informed_by"] == ["nmdc:omprc-11-bm72c549"]
    assert job_req["config"]["input_data_objects"]


#def test_scheduler_find_new_jobs_for_multi_dgns(test_db, mock_api, workflows_config_dir, site_config_file):
def test_scheduler_find_new_jobs_for_multi_dgns(test_db, test_client, workflows_config_dir, site_config_file):
    """
    Testing where db is loaded with two data generation sets with two annotations records with versions within range exist.
    This is to ensure that the loop over each dg_execution_record is keeping track of their own set of wf execution types
    correctly. Should schedule one new MAG job for nmdc:omprc-11-bm72c549 and nmdc:omprc-11-tvg68444.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_objects_multi.json", "data_object_set")
    load_fixture(test_db, "data_generation_multi.json", "data_generation_set")
    load_fixture(test_db, "workflow_execution_multi.json", "workflow_execution_set")

    workflow_config = load_workflow_configs(workflows_config_dir / "workflows.yaml")

    #scheduler = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file)
    scheduler = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file, api=test_client)
    assert scheduler

    workflow_process_nodes, manifest_map = load_workflow_process_nodes(scheduler.api, workflow_config)
    # sanity check
    assert workflow_process_nodes

    new_jobs = []
    found_jobs = []
    for node in workflow_process_nodes:
        found_jobs = scheduler.find_new_jobs(node, manifest_map, new_jobs)
        new_jobs.extend(found_jobs)
        
    assert new_jobs
    assert len(new_jobs) == 2
    
    new_job = new_jobs[0]
    assert isinstance(new_job, SchedulerJob)
    assert new_job.workflow.type == "nmdc:MagsAnalysis"
    assert new_job.trigger_act.type == "nmdc:MetagenomeAnnotation"
    assert new_job.trigger_act.data_objects_by_type

    job_req = scheduler.create_job_rec(new_job, manifest_map)
    assert job_req
    
    new_job = new_jobs[1]
    assert isinstance(new_job, SchedulerJob)
    assert new_job.workflow.type == "nmdc:MagsAnalysis"
    assert new_job.trigger_act.type == "nmdc:MetagenomeAnnotation"
    assert new_job.trigger_act.data_objects_by_type

    job_req = scheduler.create_job_rec(new_job, manifest_map)
    assert job_req

    assert job_req["config"]["activity"]["type"] == "nmdc:MagsAnalysis"
    assert job_req["config"]["input_data_objects"]


def test_scheduler_cycle_manifest(test_db, test_client, workflows_config_dir, site_config_file):
    """
    Test basic job creation for a data generation ID that is in a manifest set.
    Should return one job scheduled for the one manifest set
    This currently uses a modified dev site config so that the dev-api gets called to test the
    aggregations whereas other unit tests mock the api for minting IDs, else it will hang
    TO DO: replace live dev aggregation call for stability of offline testing 
    Results: One manifest job is scheduled, a second dgns for the same manifest is skipped, and a
    non-manifest MAGs:v1.3.16 for nmdc:wfmgan-11-6x59p192.2 is created
    Note: this used to take in 'site_config_file_dev_api' which was a fixture to use the live dev api (risky)
    now that we have local endpoint support, reverting back to standard config 20251104 -jlp
    """
    exp_rqc_git_repos = [
        "https://github.com/microbiomedata/ReadsQC",
        "https://github.com/microbiomedata/metaMAGs"
    ]
    # init_test(test_db)
    reset_db(test_db)

    load_fixture(test_db, "data_objects_in_manifest.json", "data_object_set")
    load_fixture(test_db, "data_generation_in_manifest.json", "data_generation_set")
    load_fixture(test_db, "manifest_set.json", "manifest_set")
    # Testing combining manifest data with non-manifest
    load_fixture(test_db, "data_objects_2.json", "data_object_set")
    load_fixture(test_db, "data_generation_2.json", "data_generation_set")
    load_fixture(test_db, "workflow_execution_2.json", "workflow_execution_set")


    # Scheduler will find one manifest job and one MAG to create
    exp_num_jobs_initial = 2
    exp_num_jobs_cycle_1 = 0
    #jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml",
    #               site_conf=site_config_file_dev_api)
#    jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
#                   site_conf=site_config_file_dev, api=test_client)
    jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file, api=test_client)
    
    with patch.object(jm.api, 'minter', return_value="mocked-id-123"):
        resp = jm.cycle()
        assert len(resp) == exp_num_jobs_initial
        assert resp[0]["config"]["git_repo"] in exp_rqc_git_repos

        # All jobs should now be in a submitted state
        resp = jm.cycle()
        assert len(resp) == exp_num_jobs_cycle_1


def test_scheduler_cycle_downstream_manifest(test_db, test_client, workflows_config_dir, site_config_file):
    """
    This schedules the reads based analysis and assembly downstream jobs after a manifest rqcfilter job is complete.
     """
    exp_rqc_git_repos = [
        "https://github.com/microbiomedata/ReadbasedAnalysis",
        "https://github.com/microbiomedata/metaAssembly"
    ]
    # init_test(test_db)
    reset_db(test_db)

    load_fixture(test_db, "data_objects_in_manifest_downstream.json", "data_object_set")
    load_fixture(test_db, "data_generation_in_manifest.json", "data_generation_set")
    load_fixture(test_db, "manifest_set.json", "manifest_set")

    # Load an existing and completed ReadsQC job for the manifest dgns
    load_fixture(test_db, "job_manifest_readsqc.json", "jobs")
    # Load the finished readsQC so that assembly will schedule
    load_fixture(test_db, "workflow_execution_manifest_readsqc.json", "workflow_execution_set")


    # Scheduler will find one manifest-related asm job
    exp_num_jobs_initial = 2
    exp_num_jobs_cycle_1 = 0
    
    jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file, api=test_client)
    
    with patch.object(jm.api, 'minter', return_value="mocked-id-123"):
        resp = jm.cycle()
        assert len(resp) == exp_num_jobs_initial
        assert resp[0]["config"]["git_repo"] in exp_rqc_git_repos

        # All jobs should now be in a submitted state
        resp = jm.cycle()
        assert len(resp) == exp_num_jobs_cycle_1

def test_scheduler_cycle_manifest_multi(test_db, test_client, workflows_config_dir, site_config_file):
    """
    Test basic job creation for a data generation ID that is in a manifest set.
    Should return one job scheduled for the one manifest set
    This currently uses a modified dev site config so that the dev-api gets called to test the
    aggregations whereas other unit tests mock the api for minting IDs, else it will hang
    TO DO: replace live dev aggregation call for stability of offline testing 
    Results: One manifest job is scheduled, a second dgns for the same manifest is skipped, and a
    non-manifest MAGs:v1.3.16 for nmdc:wfmgan-11-6x59p192.2 is created
    note: site_config_file_dev_api before
    """
    exp_rqc_git_repos = [
        "https://github.com/microbiomedata/ReadsQC",
    ]
    # init_test(test_db)
    reset_db(test_db)

    load_fixture(test_db, "data_objects_in_manifest_2.json", "data_object_set")
    load_fixture(test_db, "data_generation_in_manifest_2.json", "data_generation_set")
    load_fixture(test_db, "manifest_set_2.json", "manifest_set")
    

    # Scheduler will find two manifest jobs
    exp_num_jobs_initial = 2
    exp_num_jobs_cycle_1 = 0
    jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file, api=test_client)
    
    with patch.object(jm.api, 'minter', return_value="mocked-id-123"):
        resp = jm.cycle()
        assert len(resp) == exp_num_jobs_initial
        assert resp[0]["config"]["git_repo"] in exp_rqc_git_repos

        # All jobs should now be in a submitted state
        resp = jm.cycle()
        assert len(resp) == exp_num_jobs_cycle_1


def test_scheduler_manifest_multicycle(test_db, test_client, workflows_config_dir, site_config_file):
    """
    This tests a few cycle runs with manifest set. The manifest job readsQC start, 
    then fixtures are loaded to make the readsQC look complete to schedule the downstream jobs
    in the next cycle call.
    """
   
    reset_db(test_db)
    load_fixture(test_db, "data_objects_in_manifest_3.json", "data_object_set")
    load_fixture(test_db, "data_generation_in_manifest_3.json", "data_generation_set")
    load_fixture(test_db, "manifest_set_3.json", "manifest_set")

    
    # scheduler will find one ReadsQC job
    exp_num_jobs_initial = 1 
    # jobs are submitted, no new jobs
    exp_num_jobs_cycle_1 = 0 
    # scheduler with find ReadBasedAnalysis and Assembly jobs
    exp_num_jobs_cycle_2 = 2
    # jobs are submitted, no new jobs
    exp_num_jobs_cycle_3 = 0 
    
    jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file, api=test_client)
    
    with patch.object(jm.api, 'minter', return_value="mocked-id-123"):
        resp = jm.cycle()
        assert len(resp) == exp_num_jobs_initial
        assert resp[0]["config"]["activity"]["type"] == "nmdc:ReadQcAnalysis"

        # All jobs should now be in a submitted state
        resp = jm.cycle()
        assert len(resp) == exp_num_jobs_cycle_1

        #
        # Now make the ReadsQC job complete
        #
        # Load an existing and completed ReadsQC job for the manifest dgns
        # note: this doesn't update the new ReadQC job record created in cycle1 that the watcher would eventually claim, 
        # so the testdb will ignore it in this cycle and use the completed job that is loaded below. 
        load_fixture(test_db, "job_manifest_3_readsqc.json", "jobs")
        # Load the finished readsQC so that assembly and readbased taxnomy will schedule
        load_fixture(test_db, "workflow_execution_manifest_3_readsqc.json", "workflow_execution_set")

        # Schedule the next 2 jobs downstream
        resp = jm.cycle()
        assert len(resp) == exp_num_jobs_cycle_2
        

        # All jobs should now be in a submitted state
        resp = jm.cycle()
        assert len(resp) == exp_num_jobs_cycle_3


def test_scheduler_manifest_multicycle_allow(test_data_dir, test_db, test_client, workflows_config_dir, site_config_file):
    """
    Another variation of test_scheduler_manifest_multicycle but using an allow list.
    This works when testing permutations of data_generation_set IDs for the manifest set
    in the allow2.lst using nmdc:dgns-11-d4er8763jlp, nmdc:dgns-11-9ss0vs34jlp or both
    """
   
    allowlistfile = Path(test_data_dir) / "allow2.lst"
    allowlist = set()
    with open(allowlistfile) as f:
        for line in f:
            allowlist.add(line.rstrip())
    

    reset_db(test_db)
    load_fixture(test_db, "data_objects_in_manifest_3.json", "data_object_set")
    load_fixture(test_db, "data_generation_in_manifest_3.json", "data_generation_set")
    load_fixture(test_db, "manifest_set_3.json", "manifest_set")


    # Scheduler cycle expected jobs count
    exp_num_jobs_initial = 1
    exp_num_jobs_cycle_1 = 0
    exp_num_jobs_cycle_2 = 2
    exp_num_jobs_cycle_3 = 0
    
    jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file, api=test_client)
    
    with patch.object(jm.api, 'minter', return_value="mocked-id-123"):
        resp = jm.cycle(allowlist=allowlist)
        assert len(resp) == exp_num_jobs_initial
        assert resp[0]["config"]["activity"]["type"] == "nmdc:ReadQcAnalysis"

        # All jobs should now be in a submitted state
        resp = jm.cycle(allowlist=allowlist)
        assert len(resp) == exp_num_jobs_cycle_1

        #
        # Now make the ReadsQC job complete
        #
        # Load an existing and completed ReadsQC job for the manifest dgns
        # note: this doesn't update the new ReadQC job record created in cycle1 that the watcher would eventually claim, 
        # so the testdb will ignore it in this cycle and use the completed job that is loaded below. 
        load_fixture(test_db, "job_manifest_3_readsqc.json", "jobs")
        # Load the finished readsQC so that assembly and readbased taxnomy will schedule
        load_fixture(test_db, "workflow_execution_manifest_3_readsqc.json", "workflow_execution_set")

        # Schedule the next 2 jobs downstream
        resp = jm.cycle(allowlist=allowlist)
        assert len(resp) == exp_num_jobs_cycle_2
        

        # All jobs should now be in a submitted state
        resp = jm.cycle(allowlist=allowlist)
        assert len(resp) == exp_num_jobs_cycle_3


def test_scheduler_allowlist(test_data_dir, test_db, test_client, workflows_config_dir, site_config_file):
    """
    Test basic job creation for a data generation nmdc:dgns-11-qmpge038 in the allow list that is in a manifest set.
    Should return one ReadsQC job scheduled for the manifest set
    Results: One manifest job is scheduled
    
    """
    allowlistfile = Path(test_data_dir) / "allow.lst"
    allowlist = set()
    with open(allowlistfile) as f:
        for line in f:
            allowlist.add(line.rstrip())
    

    exp_rqc_git_repos = [
        "https://github.com/microbiomedata/ReadsQC",
    ]
    
    

    # Note: Can optionally use this function to test a local db copy + custom allow list by
    # 1. Modify allow.lst under test_data (or point to a new one)
    # 3. Optionally change 'test_db' dbname to backup_db (local copy) in conftest 
    #    commenting out the reset/fixture lines below. Be careful with commits -jlp20260107
    reset_db(test_db)
    load_fixture(test_db, "data_objects_in_manifest.json", "data_object_set")
    load_fixture(test_db, "data_generation_in_manifest.json", "data_generation_set")
    load_fixture(test_db, "manifest_set.json", "manifest_set")
    

    # Scheduler will find one manifest job
    exp_num_jobs_initial = 1
    exp_num_jobs_cycle_1 = 0
    jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file, api=test_client)
    
    with patch.object(jm.api, 'minter', return_value="mocked-id-123"):
        resp = jm.cycle(allowlist=allowlist)
        assert len(resp) == exp_num_jobs_initial
        assert resp[0]["config"]["git_repo"] in exp_rqc_git_repos # could change this to config.activity.type = "nmdc:ReadQcAnalysis"

        # All jobs should now be in a submitted state
        resp = jm.cycle(allowlist=allowlist)
        assert len(resp) == exp_num_jobs_cycle_1


def test_scheduler_mock_api(test_db, mock_api_small, workflows_config_dir, site_config_file):
    """ 
    Patch the NmdcRuntimeApi class itself as it's seen by the Scheduler module.
    The patch targets the class itself BEFORE instantiation.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")

    with patch('nmdc_automation.workflow_automation.sched.NmdcRuntimeApi') as MockApiClass:
        # Get a mock of the instance that will be created
        mock_api_instance = MockApiClass.return_value

        # Configure the 'mint' method on the mock instance.
        # This is where you specify the mock's behavior.
        mock_api_instance.minter.return_value = 'mocked-id-123'
    
        jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
                       site_conf=site_config_file)
        
        minted_id = jm.api.minter("test")

        assert minted_id == 'mocked-id-123'


def test_scheduler_mock_minter(test_db, test_client, workflows_config_dir, site_config_file):
    """ 
    Patch the NmdcRuntimeApi class itself as it's seen by the Scheduler module.
    The patch targets the class instantiation. This tests that when the site config is
    set to the nmdc-dev api, the mock minter is patched on the INSTANCE only. This is the 
    test 
    """
    reset_db(test_db)
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")

    jm = Scheduler(workflow_yaml=workflows_config_dir / "workflows.yaml",
                       site_conf=site_config_file, api=test_client)
    
    with patch.object(jm.api, 'minter', return_value="mocked-id-123"):
        resp = jm.cycle()
        
        assert jm.api.minter.called
        