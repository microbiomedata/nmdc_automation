from nmdc_automation.workflow_automation.sched import Scheduler, SchedulerJob, MissingDataObjectException
from pytest import mark
import pytest

from nmdc_automation.workflow_automation.workflow_process import load_workflow_process_nodes
from nmdc_automation.workflow_automation.workflows import load_workflow_configs
from tests.fixtures.db_utils import init_test, load_fixture, read_json, reset_db


@mark.parametrize("workflow_file", [
    "workflows.yaml",
    "workflows-mt.yaml"
])
def test_scheduler_cycle(test_db, mock_api, workflow_file, workflows_config_dir, site_config_file):
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
    jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / workflow_file,
                   site_conf=site_config_file)
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
def test_progress(test_db, mock_api, workflow_file, workflows_config_dir, site_config_file):
    reset_db(test_db)
    metatranscriptome = False
    if workflow_file == "workflows-mt.yaml":
        metatranscriptome = True
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")



    jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / workflow_file,
                   site_conf= site_config_file)
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


def test_multiple_versions(test_db, mock_api, workflows_config_dir, site_config_file):
    init_test(test_db)
    reset_db(test_db)
    test_db.jobs.delete_many({})

    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")

    jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file)
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


def test_out_of_range(test_db, mock_api, workflows_config_dir, site_config_file):
    init_test(test_db)
    reset_db(test_db)
    test_db.jobs.delete_many({})
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")
    jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file)
    # Let's create two RQC records.  One will be in range
    # and the other will not.  We should only get new jobs
    # for the one in range.
    load_fixture(test_db, "read_qc_analysis.json", col="workflow_execution_set")
    load_fixture(test_db, "read_qc_analysis.json", col="workflow_execution_set", version="v0.0.1")

    resp = jm.cycle()
    # there is one additional metatronscriptome rqc job from the fixture
    assert len(resp) == 2
    resp = jm.cycle()
    assert len(resp) == 0

def test_type_resolving(test_db, mock_api, workflows_config_dir, site_config_file):
    """
    This tests the handling when the same type is used for
    different activity types.  The desired behavior is to
    use the first match.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")
    load_fixture(test_db, "read_qc_analysis.json", col="workflow_execution_set")

    jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml",
                   site_conf=site_config_file)
    workflow_by_name = dict()
    for wf in jm.workflows:
        workflow_by_name[wf.name] = wf

    # mock progress
    load_fixture(test_db, "metagenome_assembly.json", col="workflow_execution_set")
    load_fixture(test_db, "metagenome_annotation.json", col="workflow_execution_set")

    resp = jm.cycle()

    assert len(resp) == 2
    # assert 'annotation' in resp[1]['config']['inputs']['contig_file']


@mark.parametrize("workflow_file", [
    "workflows.yaml",
    "workflows-mt.yaml"
])
def test_scheduler_add_job_rec(test_db, mock_api, workflow_file, workflows_config_dir, site_config_file):
    """
    Test basic job creation.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")

    jm = Scheduler(test_db, workflow_yaml=workflows_config_dir / workflow_file,
                   site_conf=site_config_file)
    # sanity check
    assert jm


def test_scheduler_find_new_jobs(test_db, mock_api, workflows_config_dir, site_config_file):
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

    workflow_process_nodes = load_workflow_process_nodes(test_db, workflow_config)
    # sanity check
    assert workflow_process_nodes

    scheduler = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file)
    assert scheduler

    new_jobs = []
    for node in workflow_process_nodes:
        new_jobs.extend(scheduler.find_new_jobs(node))
    assert new_jobs
    assert len(new_jobs) == 1
    new_job = new_jobs[0]
    assert isinstance(new_job, SchedulerJob)
    assert new_job.workflow.type == "nmdc:MagsAnalysis"
    assert new_job.trigger_act.type == "nmdc:MetagenomeAnnotation"
    assert new_job.trigger_act.data_objects_by_type

    job_req = scheduler.create_job_rec(new_job)
    assert job_req
    assert job_req["config"]["activity"]["type"] == "nmdc:MagsAnalysis"
    assert job_req["config"]["was_informed_by"] == "nmdc:omprc-11-cegmwy02"
    assert job_req["config"]["input_data_objects"]


def test_scheduler_create_job_rec_raises_missing_data_object_exception(test_db, mock_api, workflows_config_dir, site_config_file):
    """
    Test that create_job_rec raises a MissingDataObjectException for missing data files
    """
    reset_db(test_db)
    load_fixture(test_db, "data_objects_2.json", "data_object_set")
    load_fixture(test_db, "data_generation_2.json", "data_generation_set")
    load_fixture(test_db, "workflow_execution_2.json", "workflow_execution_set")

    workflow_config = load_workflow_configs(workflows_config_dir / "workflows.yaml")

    workflow_process_nodes = load_workflow_process_nodes(test_db, workflow_config)
    # sanity check
    assert workflow_process_nodes

    scheduler = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file)
    assert scheduler

    new_jobs = []
    for node in workflow_process_nodes:
        new_jobs.extend(scheduler.find_new_jobs(node))
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
        job_req = scheduler.create_job_rec(new_job)


def test_scheduler_create_job_rec_has_input_files_as_array(test_db, mock_api, workflows_config_dir, site_config_file):
    """
    Test that the input_data_objects field is an array of strings.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_object_set.json")
    load_fixture(test_db, "data_generation_set.json")
    load_fixture(test_db, "read_qc_analysis.json", col="workflow_execution_set")

    jm = Scheduler(
        test_db, workflow_yaml=workflows_config_dir / "workflows.yaml",
        site_conf=site_config_file
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
def test_scheduler_find_new_jobs_with_existing_job(job_fixture, test_db, workflows_config_dir, site_config_file):
    """
    Test that the find_new_jobs method works as expected. We load an existing job fixture so we expect no new jobs to be found.
    """
    reset_db(test_db)
    load_fixture(test_db, "data_objects_2.json", "data_object_set")
    load_fixture(test_db, "data_generation_2.json", "data_generation_set")
    load_fixture(test_db, "workflow_execution_2.json", "workflow_execution_set")
    load_fixture(test_db, job_fixture, "jobs")

    workflow_config = load_workflow_configs(workflows_config_dir / "workflows.yaml")

    workflow_process_nodes = load_workflow_process_nodes(test_db, workflow_config)
    # sanity check
    assert workflow_process_nodes

    scheduler = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file)
    assert scheduler

    new_jobs = []
    for node in workflow_process_nodes:
        new_jobs.extend(scheduler.find_new_jobs(node))
    assert not new_jobs

def test_scheduler_find_new_jobs3(test_db, mock_api, workflows_config_dir, site_config_file):
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

    workflow_process_nodes = load_workflow_process_nodes(test_db, workflow_config)
    # sanity check
    assert workflow_process_nodes

    scheduler = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file)
    assert scheduler

    new_jobs = []
    for node in workflow_process_nodes:
        new_jobs.extend(scheduler.find_new_jobs(node))
    assert new_jobs
    assert len(new_jobs) == 1
    new_job = new_jobs[0]
    assert isinstance(new_job, SchedulerJob)
    assert new_job.workflow.type == "nmdc:MagsAnalysis"
    assert new_job.trigger_act.type == "nmdc:MetagenomeAnnotation"
    assert new_job.trigger_act.data_objects_by_type

    job_req = scheduler.create_job_rec(new_job)
    assert job_req
    
    #new_job = new_jobs[1]
    #job_req = scheduler.create_job_rec(new_job)
    #assert job_req

    assert job_req["config"]["activity"]["type"] == "nmdc:MagsAnalysis"
    assert job_req["config"]["was_informed_by"] == "nmdc:omprc-11-bm72c549"
    assert job_req["config"]["input_data_objects"]


def test_scheduler_find_new_jobs_for_multi_dgns(test_db, mock_api, workflows_config_dir, site_config_file):
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

    workflow_process_nodes = load_workflow_process_nodes(test_db, workflow_config)
    # sanity check
    assert workflow_process_nodes

    scheduler = Scheduler(test_db, workflow_yaml=workflows_config_dir / "workflows.yaml", site_conf=site_config_file)
    assert scheduler

    new_jobs = []
    for node in workflow_process_nodes:
        new_jobs.extend(scheduler.find_new_jobs(node))
    assert new_jobs
    assert len(new_jobs) == 2
    
    new_job = new_jobs[0]
    assert isinstance(new_job, SchedulerJob)
    assert new_job.workflow.type == "nmdc:MagsAnalysis"
    assert new_job.trigger_act.type == "nmdc:MetagenomeAnnotation"
    assert new_job.trigger_act.data_objects_by_type

    job_req = scheduler.create_job_rec(new_job)
    assert job_req
    
    new_job = new_jobs[1]
    assert isinstance(new_job, SchedulerJob)
    assert new_job.workflow.type == "nmdc:MagsAnalysis"
    assert new_job.trigger_act.type == "nmdc:MetagenomeAnnotation"
    assert new_job.trigger_act.data_objects_by_type

    job_req = scheduler.create_job_rec(new_job)
    assert job_req

    assert job_req["config"]["activity"]["type"] == "nmdc:MagsAnalysis"
    assert job_req["config"]["input_data_objects"]

