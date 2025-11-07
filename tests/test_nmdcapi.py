from nmdc_automation.api.nmdcapi import NmdcRuntimeApi as nmdcapi
import json
import os
import time

from unittest.mock import patch, PropertyMock, Mock
from tests.fixtures.db_utils import load_fixture, reset_db

#def test_basics(requests_mock, site_config_file, mock_api):
def test_basics(monkeypatch, requests_mock, site_config_file, test_client):
    #n = nmdcapi(site_config_file)
    n = test_client

    # Temporarily bind the REAL method to the mock instance
    monkeypatch.setattr(n, "get_object", nmdcapi.get_object.__get__(n, nmdcapi))

    # Add decode description
    resp = {'description': '{"a": "b"}'}
    requests_mock.get("http://localhost:8000/objects/xxx", json=resp)
    resp = n.get_object("xxx", decode=True)
    assert resp is not None
    assert "metadata" in resp


def test_objects(monkeypatch, requests_mock, site_config_file, test_data_dir, test_client):
    #n = nmdcapi(site_config_file)
    n = test_client

    # Temporarily bind the REAL method to the mock instance
    monkeypatch.setattr(n, "create_object", nmdcapi.create_object.__get__(n, nmdcapi))
    monkeypatch.setattr(n, "post_workflow_executions", nmdcapi.post_workflow_executions.__get__(n, nmdcapi))
    monkeypatch.setattr(n, "set_type", nmdcapi.set_type.__get__(n, nmdcapi))
    monkeypatch.setattr(n, "bump_time", nmdcapi.bump_time.__get__(n, nmdcapi))

    requests_mock.post("http://localhost:8000/objects", json={})
    fn = test_data_dir / "afile.sha256"
    if os.path.exists(fn):
        os.remove(fn)
    afile = test_data_dir / "afile"
    resp = n.create_object(str(afile), "desc", "http://localhost:8000/")
    resp = n.create_object(test_data_dir / "afile", "desc", "http://localhost:8000/")
    url = "http://localhost:8000/workflows/workflow_executions"
    requests_mock.post(url, json={"a": "b"})
    resp = n.post_workflow_executions({"a": "b"})
    assert "a" in resp

    requests_mock.put("http://localhost:8000/objects/abc/types", json={})
    resp = n.set_type("abc", "metadatain")

    requests_mock.patch("http://localhost:8000/objects/abc", json={"a": "b"})
    resp = n.bump_time("abc")
    assert "a" in resp


def test_list_funcs(monkeypatch, requests_mock, site_config_file, test_data_dir, test_client):
   #n = nmdcapi(site_config_file)
    n = test_client
    mock_resp = json.load(open(test_data_dir / "mock_jobs.json"))

    # Temporarily bind the REAL method to the mock instance
    monkeypatch.setattr(n, "list_jobs", nmdcapi.list_jobs.__get__(n, nmdcapi))
    monkeypatch.setattr(n, "list_ops", nmdcapi.list_ops.__get__(n, nmdcapi))
    monkeypatch.setattr(n, "list_objs", nmdcapi.list_objs.__get__(n, nmdcapi))
    

    # TODO: check the full url
    requests_mock.get("http://localhost:8000/jobs", json=mock_resp)
    resp = n.list_jobs(filt="a=b")
    assert resp is not None

    requests_mock.get("http://localhost:8000/operations", json=[])
    resp = n.list_ops(filt="a=b")
    assert resp is not None

    requests_mock.get("http://localhost:8000/objects", json=[])
    resp = n.list_objs(filt="a=b")
    assert resp is not None


def test_update_op(monkeypatch, requests_mock, site_config_file, test_client):
    #n = nmdcapi(site_config_file)
    n = test_client

    mock_resp = {'metadata': {"b": "c"}}

    # Temporarily bind the REAL method to the mock instance
    monkeypatch.setattr(n, "update_op", nmdcapi.update_op.__get__(n, nmdcapi))
    monkeypatch.setattr(n, "get_op", nmdcapi.get_op.__get__(n, nmdcapi))
    
    # monkeypatch.setattr(requests, "get", mock_get)
    requests_mock.get("http://localhost:8000/operations/abc", json=mock_resp)
    requests_mock.patch("http://localhost:8000/operations/abc", json=mock_resp)
    # monkeypatch.setattr(requests, "get", mock_get)
    # monkeypatch.setattr(requests, "patch", mock_patch)
    resp = n.update_op("abc", done=True, results={"a": "b"}, meta={"d": "e"})
    assert "b" in resp["metadata"]


def test_jobs(monkeypatch, requests_mock, site_config_file, test_client):
    #n = nmdcapi(site_config_file)
    n = test_client

    # Temporarily bind the REAL method to the mock instance
    monkeypatch.setattr(n, "get_job", nmdcapi.get_job.__get__(n, nmdcapi))
    monkeypatch.setattr(n, "claim_job", nmdcapi.claim_job.__get__(n, nmdcapi))

    requests_mock.get("http://localhost:8000/jobs/abc", json="jobs/")
    resp = n.get_job("abc")
    assert "jobs/" in resp

    resp = {"url": "jobs:claim"}
    url = "http://localhost:8000/jobs/abc:claim"
    requests_mock.post(url, json=resp, status_code=200)
    resp = n.claim_job("abc")
    assert ":claim" in resp["url"]
    assert resp["claimed"] is False

    requests_mock.post(url, json={}, status_code=409)
    resp = n.claim_job("abc")
    assert resp["claimed"] is True


def test_nmdcapi_get_token_with_retry(monkeypatch, requests_mock, site_config_file, test_client):
    #n = nmdcapi(site_config_file)
    n = test_client
    token_url = "http://localhost:8000/token"

    monkeypatch.setattr(n, "get_token", nmdcapi.get_token.__get__(n, nmdcapi))

    requests_mock.post(
        token_url, [{"status_code": 401, "json": {"error": "Unauthorized"}},
                    {"status_code": 200, "json": {
                        "access_token": "mocked_access_token",
                        "expires": {"days": 1},
                    }}]
    )
    # sanity check
    #assert n.token is None
    #assert n.expires_at == 0

    # Call method under test - should retry and succeed
    n.get_token()

    # Check that the token was set
    assert n.token == "mocked_access_token"
    assert n.expires_at > 0


def test_nmdcapi_get_token_live(test_client): 
    """
    Tests actual token acquisition against the live running local API endpoint.
    """
    # Arrange: Instantiate the client. 
    # nmdcapi must be initialized with access to the site_config object,
    # either directly or by reading from the site_config_file path.
    
    # We use the site_config object to get the necessary connection details for the client
    #auth_config = site_config.get_api_auth_config()
    
    # Assuming nmdcapi takes its initialization parameters from the config file it reads
    #n = nmdcapi(site_config) 
    n = test_client
    
    # Sanity check before the call
    #assert n.token is None
    #assert n.expires_at == 0

    # Act: Call the method under test - this now hits the real http://127.0.0.1:8000/token
    n.get_token()

    # Assert: Check that the token was successfully acquired
    assert n.token is not None
    assert isinstance(n.token, str)
    assert len(n.token) > 10 # Check for a reasonable token length
    
    # Check that the expiration time was set to a future value
    # We can check against the current time + a buffer (e.g., 5 seconds)
    assert n.expires_at > time.time() + 5


def test_run_query(test_db, test_client):
    reset_db(test_db)
     
    # Test aggregation data set will return 38 documents
    load_fixture(test_db, "data_object_set.agg.json", "data_object_set")
    load_fixture(test_db, "data_generation.agg.json", "data_generation_set")

    api = test_client 

    manifest_agg = {
        "aggregate": "data_generation_set",
        "pipeline": [
            {
                "$match": {
                    "associated_studies": {
                        "$in": [
                            "nmdc:sty-11-pzmd0x14",
                            "nmdc:sty-11-hht5sb92"
                        ]
                    } 
                }
            },
            {
                "$lookup": {
                    "from": "data_object_set",
                    "localField": "has_output",
                    "foreignField": "id",
                    "as": "data_object_set"
                }
            },
            {
                "$match": {
                    "data_object_set.in_manifest": {
                    "$exists": True
                    }
                }
            }
        ]
    }

    
    resp = api.run_query(manifest_agg)
    assert resp
    # TODO This and the side_effect need to be changed to not pass the raw response structure
    assert len(resp['cursor']['batch']) == 38


@patch('nmdc_automation.api.nmdcapi.NmdcRuntimeApi._run_query_single') 
def test_run_query_pagination(mock_run_query_single, site_config_file, mock_api_small, response_call1, response_call2):
    
    mock_run_query_single.side_effect = [response_call1, response_call2]
    
    # In this test, I don't want to use 'test_client', which will the trigger the globally active mock for run_query
    # Instead, go the traditional route for the api mock so that I can use the real run_query and target the
    # helper function for testing pagination

    api= nmdcapi(site_config_file) 

    # we want to mimic run_query batch size of 25, We have 42 entries returned in 2 pages(25 in page1 and 17 in page2)
    expected_total_count = len(response_call1['cursor']['batch']) + len(response_call2['cursor']['batch'])

    manifest_agg = {
        "aggregate": "data_generation_set",
        "pipeline": [
            {
                "$match": {
                    "associated_studies": {
                        "$in": [
                            "nmdc:sty-11-pzmd0x14",
                            "nmdc:sty-11-hht5sb92"
                        ]
                    } 
                }
            },
            {
                "$lookup": {
                    "from": "data_object_set",
                    "localField": "has_output",
                    "foreignField": "id",
                    "as": "data_object_set"
                }
            },
            {
                "$match": {
                    "data_object_set.in_manifest": {
                    "$exists": True
                    }
                }
            }
        ]
    }

    results = api.run_query(manifest_agg)
    assert isinstance(results, list) 
    assert len(results) == expected_total_count
    


