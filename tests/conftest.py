import ast
import configparser
import json
import os
from pymongo import MongoClient
from pathlib import Path
from pytest import fixture
import requests
import requests_mock
import shutil
from time import time
import pandas as pd
import json
from yaml import load, Loader
from unittest.mock import MagicMock, patch
import logging
from typing import Callable


from nmdc_automation.config import SiteConfig
from nmdc_automation.models.workflow import WorkflowConfig
from tests.fixtures import db_utils
from nmdc_automation.workflow_automation.wfutils import WorkflowJob
from nmdc_automation.api.nmdcapi import NmdcRuntimeApi as nmdcapi
from jaws_client.config import Configuration


logger = logging.getLogger(__name__) 
logger.setLevel(logging.DEBUG)


@fixture(scope="session")
def mock_job_state():
    state = db_utils.read_json(
        "mags_workflow_state.json"
    )
    return state

@fixture(scope="session")
def mock_nucleotide_sequencing():
    return {
        "id": "nmdc:omprc-11-metag1",
        "name": "Test Metagenome Processing",
        "has_input": [
            "nmdc:bsm-11-qezc0h51"
        ],
        "has_output": [
            "nmdc:dobj-11-rawreads1",
            "nmdc:dobj-11-rawreads2"
        ],
        "analyte_category": "metagenome",
        "associated_studies": [
            "nmdc:sty-11-test001"
        ],
        "processing_institution": "JGI",
        "principal_investigator": {
            "has_raw_value": "PI Name",
            "email": "pi_name@example.com",
            "name": "PI Name",
            "type": "nmdc:PersonValue"
        },
        "type": "nmdc:NucleotideSequencing"
    }


@fixture(scope="session")
def mock_metagenome_assembly():
    return

@fixture(scope="session")
def mags_config(fixtures_dir)->WorkflowConfig:
    yaml_file = fixtures_dir / "mags_config.yaml"
    wf = load(open(yaml_file), Loader)
    # normalize the keys from Key Name to key_name
    wf = {k.replace(" ", "_").lower(): v for k, v in wf.items()}
    return WorkflowConfig(**wf)

@fixture(scope="function")
def mock_api_small(monkeypatch, requests_mock):
    monkeypatch.setenv("NMDC_API_URL", "http://localhost")
    monkeypatch.setenv("NMDC_CLIENT_ID", "anid")
    monkeypatch.setenv("NMDC_CLIENT_SECRET", "asecret")
    token_resp = {"expires": {"minutes": time()+60},
            "access_token": "abcd"
            }
    requests_mock.post("http://localhost:8000/token", json=token_resp)

    resp = ["nmdc:dobj-01-abcd4321"]
    # mock mint responses in sequence
    requests_mock.post("http://localhost:8000/pids/mint", json=resp)
    requests_mock.post("http://localhost:8000/pids/bind", json=resp)


@fixture(scope="session")
def test_db_old():
    conn_str = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    return MongoClient(conn_str).test

@fixture(scope="session")
def test_db(site_config):

    # Note: if your local API is up, ensure this is set up, else you will get failed tests
    # due to a local instance of mongo not coordinating with the API's mongo backend
    local_mongo_cfg = site_config.get_local_mongodb_config

    # If there is no local runtime config found, connect to the usual local mongodb instance
    # and default will use mock API
    if not local_mongo_cfg:
        #raise ValueError("MongoDB configuration block is missing from test site config.")
        conn_str = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        return MongoClient(conn_str).test

    user = local_mongo_cfg.get("username")
    password = local_mongo_cfg.get("password")
    host = local_mongo_cfg.get("host", "localhost")
    port = local_mongo_cfg.get("port", 27018)
    auth_source = local_mongo_cfg.get("auth_source", "admin")
    DB_NAME_FOR_TESTS = local_mongo_cfg.get("database", "test")

    # runtime's docker-compose.yml is set up with mongodb credentials unless you
    # manually change it not to.
    if not user or not password:
        raise ValueError(
            "MongoDB 'username' and 'password' must be defined in the [local_runtime_mongodb] section."
        )
    
    # Build URI with the necessary flags 
    conn_str = (
        f"mongodb://{user}:{password}@{host}:{port}/{DB_NAME_FOR_TESTS}"
        f"?authSource={auth_source}&directConnection=true"
    )

    # Test without credentials
    #conn_str = (
    #    f"mongodb://{host}:{port}/{DB_NAME_FOR_TESTS}"
    #    f"?authSource={auth_source}&directConnection=true"
    #)

    client = MongoClient(conn_str)
    
    # Optional: Quick check to verify connection (good practice)
    try:
        client.admin.command('ping') 
    except Exception as e:
        raise ConnectionError(f"Failed to connect to Docker MongoDB using URI: {conn_str}. Error: {e}")
    

    return client[DB_NAME_FOR_TESTS]


# Default monkeypath is function scope, but we need a custom session scop so we can call it from
# the session-scoped fixture mock_api_setup (else it complains)
@fixture(scope="session")
def session_monkeypatch():
    from _pytest.monkeypatch import MonkeyPatch
    m = MonkeyPatch()
    yield m
    m.undo()

# Default request_mock needs to be set as custom session scope so that core API availability
# is only checked once per session and not before each individual test
@fixture(scope="session")
def session_requests_mock(request):
    """Provides a requests_mock.Mocker object with session scope."""
    import requests_mock
    m = requests_mock.Mocker()
    m.start()
    request.addfinalizer(m.stop)
    return m



@fixture(scope="session")
def configured_api_mock(session_monkeypatch, test_db, test_data_dir):

    # Create a mock for the API object
    mock_api = MagicMock(spec=nmdcapi)
    
    # Inject the actual database client into the mock for testing logic 
    # (This allows the function to query fixtures loaded into test_db)
    mock_api.client = test_db.client

    def mock_list_from_collection_side_effect(collection_name, query_filter=None, projection_fields=None):
        projection = None
        if projection_fields:
            # Create a dictionary for MongoDB projection: {'field': 1, 'another_field': 1}
            # Split the comma-delimited string, strip whitespace, and filter out any empty strings
            field_list = [f.strip() for f in projection_fields.split(',') if f.strip()]
            
            if field_list:
                # Create the inclusion projection dictionary
                projection = {field: 1 for field in field_list}
                
                # Explicitly exclude the _id field if it wasn't requested
                if '_id' not in projection:
                    projection['_id'] = 0

        collection = test_db[collection_name] 
        cursor = collection.find(query_filter if query_filter else {}, projection)
        return list(cursor)

    mock_api.list_from_collection.side_effect = mock_list_from_collection_side_effect

    def mock_run_query_side_effect(api_filter, *args, **kwargs):
        if isinstance(api_filter, dict) and 'aggregate' in api_filter:
            collection_name = api_filter.get("aggregate")
            pipeline = api_filter.get("pipeline", [])
            logger.debug(f"{pipeline}")
        
        if collection_name and pipeline:
            
            collection = test_db[collection_name]
            
            try:
                result_list = list(collection.aggregate(pipeline))
                
                # endpoint now takes care of formating the response content to a list so 
                # no not need to reformat it as below. Keeping this here in case anything changes for now -jlp 20251106
                #
                # Format the result to the expected API cursor structure for queries run endpoint
                #api_response = {
                #    "ok": 1,
                #    "cursor": {
                #        "id": None, 
                #        "batch": result_list 
                #    }
                #}
                #return api_response

                return result_list
            
            except Exception as e:
                print(f"Error during aggregation on {collection_name}: {e}")
                # Re-raise the exception or return a relevant error message/default
                raise
        return []

    mock_api.run_query.side_effect = mock_run_query_side_effect

    def mock_create_job_side_effect(job_record):

        # Ensure job_record is a dictionary if it came in as a JSON string
        if isinstance(job_record, str):
            job_data = json.loads(job_record)
        else:
            job_data = job_record

        job_data["id"] = "new-job1234"

        result = test_db.jobs.insert_one(job_data)

        return job_data
        
    mock_api.create_job.side_effect = mock_create_job_side_effect

    def mock_list_jobs_side_effect(query_filter):

        cursor = test_db.jobs.find(query_filter if query_filter else {})
        return list(cursor)
        
    mock_api.list_jobs.side_effect = mock_list_jobs_side_effect


    mock_api._base_url = "http://localhost:8000/" 
    mock_api.header = {
        'Authorization': 'Bearer abcd', 
        'Content-Type': 'application/json' 
    }

    mock_api.minter = MagicMock()
    mock_api.minter.return_value = ["nmdc:dobj-01-abcd4321"]

    session_monkeypatch.setenv("NMDC_API_URL", "http://localhost")
    session_monkeypatch.setenv("NMDC_CLIENT_ID", "anid")
    session_monkeypatch.setenv("NMDC_CLIENT_SECRET", "asecret")
    #token_resp = {"expires": {"minutes": time()+60},
    #        "access_token": "abcd"
    #        }
    #session_requests_mock.post("http://localhost:8000/token", json=token_resp)


    # 1. Custom function to set state directly
    def mock_get_token(self):
        self.token = "fake_test_token_from_mock"
        self.expires_at = time() + 3600 # Guaranteed future time

    # 2. Bind the CUSTOM function to the mock instance
    mock_api.get_token = mock_get_token.__get__(mock_api, nmdcapi) 

    # 3. Call it to initialize the mock's state
    mock_api.get_token()

    #resp = ["nmdc:dobj-01-abcd4321"]
    # mock mint responses in sequence

    #session_requests_mock.post("http://localhost:8000/pids/mint", json=resp)
    #session_requests_mock.post(
    #    "http://localhost:8000/workflows/workflow_executions",
    #    json=resp
    #    )
    #session_requests_mock.post("http://localhost:8000/pids/bind", json=resp)

    #rqcf = test_data_dir / "rqc_response2.json"
    #rqc = json.load(open(rqcf))
    #rqc_resp = {"resources": [rqc]}
    #session_requests_mock.get("http://localhost:8000/jobs", json=rqc_resp)
    
    #session_requests_mock.patch("http://localhost:8000/operations/nmdc:1234", json={})
    #session_requests_mock.get("http://localhost:8000/operations/nmdc:1234", json={'metadata': {}})


    return mock_api

# Helper to check API availability (adjust URL/check method as needed)
def is_api_available(site_config):
    """Attempt a simple status check on the local API URL."""
    try:
        base_url = site_config.api_url 
        
        # Check that the api page is up
        response = requests.get(f"{base_url}/", timeout=1)
        if response.status_code != 200:
            logger.warning(
                    f"API is UP but check failed: Received status code {response.status_code} "
                    f"from {base_url}/. Using mock API."
                )
        return response.status_code == 200
    
    except requests.exceptions.RequestException as e:
        logger.error(f"API is DOWN: Connection failed to {base_url}/. Error: {e.__class__.__name__}: {e}")
        return False

@fixture(scope="session")
def test_client(site_config, request):
#def test_client(site_config, configured_api_mock):
    """
    Provides the real NmdcApi instance if available, otherwise returns a mock.
    """
    if is_api_available(site_config):
        # Initialize and return the real API client
        return nmdcapi(site_config)
    else:
        return request.getfixturevalue("configured_api_mock")



@fixture(scope="session")
def base_test_dir():
    return Path(__file__).parent

@fixture(scope="session")
def jaws_token_file(base_test_dir):
    return base_test_dir.parent / ".local/jaws.conf"

@fixture(scope="session")
def jaws_test_token_file(base_test_dir):
    return base_test_dir / "jaws-test-token.conf"

@fixture(scope="session")
def jaws_config_file_test(base_test_dir):
    return base_test_dir / "jaws-test.conf"

@fixture(scope="session")
def jaws_config_file_integration(base_test_dir):
    return base_test_dir / "jaws-integration.conf"

@fixture(scope="session")
def fixtures_dir(base_test_dir):
    path = base_test_dir / "fixtures"
    # get the absolute path
    return path.resolve()

@fixture(scope="session")
def test_data_dir(base_test_dir):
    return base_test_dir / "test_data"

@fixture(scope="session")
def workflows_config_dir(base_test_dir):
    return base_test_dir.parent / "nmdc_automation/config/workflows"


@fixture(scope="session")
def site_config_file(base_test_dir):
    return base_test_dir / "site_configuration_test.toml"

@fixture(scope="session")
def site_config(site_config_file):
    return SiteConfig(site_config_file)

# New fixture to selectively use the dev API for queries
@fixture
def site_config_file_dev_api(site_config_file, tmp_path):
    
    # Create a path for the new temporary file.
    temp_config = tmp_path / "site_configuration_test_dev_api.toml"

    dev_api = 'api_url = "https://api-dev.microbiomedata.org"\n'

    # read the content of the original TOML file
    with open(site_config_file, "r") as f, \
         open(temp_config, "w") as nf:
        
        for line in f:
            if line.strip().startswith("api_url ="):
                nf.write(dev_api)
            else:
                nf.write(line)


    # Return the new config with api mod
    return temp_config

@fixture
def initial_state_file_1_failure(fixtures_dir, tmp_path):
    state_file = fixtures_dir / "agent_state_1_failure.json"
    # make a working copy in tmp_path
    copied_state_file = tmp_path / "agent_state_1_failure.json"
    shutil.copy(state_file, copied_state_file)
    return copied_state_file

@fixture
def response_call1(fixtures_dir):
    file_path = fixtures_dir / "response_page1.json"
    with open(file_path, 'r') as f:
        return json.load(f)
    
    
@fixture
def response_call2(fixtures_dir):
    file_path = fixtures_dir / "response_page2.json"
    with open(file_path, 'r') as f:
        return json.load(f)

@fixture

def job_metadata_factory(base_test_dir: Path) -> Callable[[Path], dict]:
    """
    A fixture that acts as a factory for loading and modifying job metadata JSON files.
    
    This returns a callable that takes a Path to a JSON file.
    The callable loads the file and substitutes 'test_pscratch' with a full path.
    """
    def _modified_job_metadata(json_path: Path) -> dict:
        """
        Loads any job_metadata.json, substitutes the relative paths defined for the outputs, 
        and modifies them to the full path so that tests can work from any repo loc
        """
        #json_path = fixtures_dir / "mags_job_metadata.json"
        
        # Read the JSON file content as a single string
        with open(json_path, "r") as f:
            file_content = f.read()

        # Substitute "test_pscratch" with "test_base_dir/test_pscratch"
        # This happens on the raw string content of the file.
        modified_content = file_content.replace("test_pscratch", f"{base_test_dir}/test_pscratch")

        # Load the modified string back into a Python dictionary
        return json.loads(modified_content)
    
    return _modified_job_metadata

@fixture
def mock_womtool_validation(mocker):
    """
    Mocks the validate_womtool_path method to prevent FileNotFoundError.
    """
    # This line replaces the original method with a mock that does nothing.
    mocker.patch.object(Configuration, 'validate_womtool_path', return_value=None)


# Sample Cromwell API responses
CROMWELL_SUCCESS_RESPONSE = {
    "id": "cromwell-job-id-12345",
    "status": "Succeeded",
    "outputs": {
        "output_file": "/path/to/output.txt"
    }
}

CROMWELL_FAIL_RESPONSE = {
    "id": "cromwell-job-id-54321",
    "status": "Failed",
    "failures": [
        {"message": "Error processing job"}
    ]
}

JOB_SUBMIT_RESPONSE = {
    "id": "cromwell-workflow-id",
  "status": "Submitted",
  "submission": "2024-10-13T12:34:56.789Z",
  "workflowName": "workflow_name",
  "workflowRoot": "gs://path/to/workflow/root",
  "metadataSource": "Unarchived",
  "outputs": {},
  "labels": {
    "label1": "value1",
    "label2": "value2"
  },
  "parentWorkflowId": None,
  "rootWorkflowId": "cromwell-root-id"
}

@fixture
def mock_cromwell_api(fixtures_dir):
    successful_job_metadata = json.load(open(fixtures_dir / 'cromwell/succeeded_metadata.json'))
    with requests_mock.Mocker() as m:
        # Mock the Cromwell submit job endpoint
        m.post('http://localhost:8088/api/workflows/v1', json=JOB_SUBMIT_RESPONSE, status_code=201)

        # Mock Cromwell status check endpoint
        m.get(
            'http://localhost:8088/api/workflows/v1/cromwell-job-id-12345/status', json={
                "id": "cromwell-job-id-12345",
                "status": "Succeeded"
            }
            )

        # Mock Cromwell failure scenario
        m.get('http://localhost:8088/api/workflows/v1/cromwell-job-id-54321/status', json=CROMWELL_FAIL_RESPONSE)

        # Mock Cromwell metadata endpoint
        m.get(
            'http://localhost:8088/api/workflows/v1/cromwell-job-id-12345/metadata',
            json=successful_job_metadata
            )

        yield m

@fixture(scope="session")
def mock_jaws_api():
    with patch("jaws_client.api.JawsApi") as mock_jaws_api:
        yield mock_jaws_api

@fixture(scope="session")
def gold_import_dir(fixtures_dir):
    return fixtures_dir / "gold_import"

@fixture(scope="session")
def gold_import_files(gold_import_dir):
    # return the full paths to fixtures that simulate JGI import files. These are used to test the GoldMapper class.
    # One (1) file is a nucleotide sequencing file. All the other files are RQC, assembly, MAGs, etc.
    return [str(f) for f in gold_import_dir.iterdir() if f.is_file()]

@fixture(scope="session")
def import_config():
    config = configparser.ConfigParser()
    config.read(Path(__file__).parent / "fixtures" / "import_config.ini")
    return config

@fixture(scope="session")
def import_config_file():
    return Path(__file__).parent / "fixtures" / "import_config.ini"


class MockNmdcRuntimeApi:
    def __init__(self):
        self.counter = 10

    def minter(self, id_type):
        type_code_map = {
            "nmdc:DataObject": "nmdc:dobj",
            "nmdc:MetagenomeAssembly": "nmdc:wfmgas",
            "nmdc:MetagenomeAnnotation": "nmdc:wfmgan",
            "nmdc:MagsAnalysis": "nmdc:wfmag",
            "nmdc:ReadQcAnalysis": "nmdc:wfrqc",
            "nmdc:ReadBasedTaxonomyAnalysis": "nmdc:wfrbt",
        }
        self.counter += 1
        prefix = type_code_map[id_type]
        return f"{prefix}-{self.counter:02d}-abcd1234"

    def get_token(self):
        return {"expires": {"minutes": time()+60},
            "access_token": "abcd"
            }

    def refresh_token(self):
        return {"expires": {"minutes": time()+60},
            "access_token": "abcd"
            }

    def get_object(self, id):
        return {
            "id": id,
            "name": "Test Object",
            "type": "nmdc:DataObject"
        }


@fixture(scope="session")
def mock_nmdc_runtime_api():
    return MockNmdcRuntimeApi()


@fixture
def grow_analysis_df(fixtures_dir):
    grow_analysis_df = pd.read_csv(fixtures_dir / "grow_analysis_projects.csv")
    grow_analysis_df.columns = [
        "apGoldId",
        "studyId",
        "itsApId",
        "project_name",
        "biosample_id",
        "seq_id",
        "file_name",
        "file_status",
        "file_size",
        "jdp_file_id",
        "md5sum",
        "analysis_project_id",
    ]
    grow_analysis_df = grow_analysis_df[
        [
            "apGoldId",
            "studyId",
            "itsApId",
            "project_name",
            "biosample_id",
            "seq_id",
            "file_name",
            "file_status",
            "file_size",
            "jdp_file_id",
            "md5sum",
            "analysis_project_id",
        ]
    ]
    # grow_analysis_df["project_name"] = grow_analysis_df["project_name"].apply(ast.literal_eval)
    return grow_analysis_df

@fixture
def jgi_staging_config(fixtures_dir, tmp_path):
    config_file = fixtures_dir / "jgi_staging_config.ini"
    config = configparser.ConfigParser()
    read_files = config.read(config_file)
    if not read_files:
        raise FileNotFoundError(f"Config file {config_file} not found.")
    # set Globus root dir to tmp_path
    config["GLOBUS"]["globus_root_dir"] = str(tmp_path)
    return config