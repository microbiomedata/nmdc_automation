from nmdc_automation.api.nmdcapi import NmdcRuntimeApi as nmdcapi
import json
from unittest.mock import patch
from tests.fixtures.db_utils import load_fixture, reset_db

def test_objects(monkeypatch, requests_mock, test_client):
    #n = nmdcapi(site_config_file)
    n = test_client

    # Temporarily bind the REAL method to the mock instance
    monkeypatch.setattr(n, "post_workflow_executions", nmdcapi.post_workflow_executions.__get__(n, nmdcapi))
    url = "http://localhost:8000/metadata/json:submit"
    requests_mock.post(url, json={"a": "b"})
    resp = n.post_workflow_executions({"a": "b"})
    assert "a" in resp


def test_list_funcs(monkeypatch, requests_mock, site_config_file, test_data_dir, test_client):
   #n = nmdcapi(site_config_file)
    n = test_client
    mock_resp = json.load(open(test_data_dir / "mock_jobs.json"))

    # Temporarily bind the REAL method to the mock instance
    monkeypatch.setattr(n, "list_jobs", nmdcapi.list_jobs.__get__(n, nmdcapi))
    
    # TODO: check the full url
    requests_mock.get("http://localhost:8000/nmdcschema/jobs", json=mock_resp)
    resp = n.list_jobs(filt="a=b")
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
    assert len(resp) == 38


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
        