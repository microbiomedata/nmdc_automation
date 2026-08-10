from nmdc_automation.api.nmdcapi import NmdcRuntimeApi as nmdcapi
import json
import logging
import pytest
from unittest.mock import patch
from tests.fixtures.db_utils import load_fixture, reset_db

def test_nmdc_client_minter(configured_api_mock):
    api = configured_api_mock
    minted_id = api.minter("nmdc:DataObject")
    assert isinstance(minted_id, str), f"Expected single minted ID to be a string, got {type(minted_id)}"
    assert minted_id.startswith("nmdc:dobj-")

def test_nmdc_client_get_object(test_db, configured_api_mock):
    reset_db(test_db)
    test_db.data_object_set.insert_one({
        "id": "nmdc:dobj-11-rhjsg657",
        "name": "Test Object",
        "description": json.dumps({"a": 1}),
        "type": "nmdc:DataObject",
    })

    api = configured_api_mock
    obj_info = api.get_object("nmdc:dobj-11-rhjsg657", decode=True)

    assert isinstance(obj_info, dict)
    assert "metadata" in obj_info

def test_nmdc_client_list_from_collection(test_db, configured_api_mock):
    reset_db(test_db)
    test_db.data_object_set.insert_one({
        "id": "nmdc:dobj-11-rhjsg657",
        "name": "Test Object",
        "type": "nmdc:DataObject",
    })

    api = configured_api_mock
    obj_info = api.list_from_collection(collection="data_object_set", filt={"id": "nmdc:dobj-11-rhjsg657"}, projection=None, max=100)

    assert isinstance(obj_info, list)
    assert isinstance(obj_info[0], dict)

def test_list_funcs(monkeypatch, requests_mock, site_config_file, test_data_dir, test_client):
   #n = nmdcapi(site_config_file)
    n = test_client
    mock_resp = json.load(open(test_data_dir / "mock_jobs.json"))

    # Temporarily bind the REAL method to the mock instance
    monkeypatch.setattr(n, "list_jobs", nmdcapi.list_jobs.__get__(n, nmdcapi))
    
    # TODO: check the full url
    requests_mock.get("http://localhost:8000/jobs", json=mock_resp)
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

def test_jobs(monkeypatch, requests_mock, site_config_file, test_client):
    #n = nmdcapi(site_config_file)
    n = test_client

    # Temporarily bind the REAL method to the mock instance
    monkeypatch.setattr(n, "claim_job", nmdcapi.claim_job.__get__(n, nmdcapi))

    resp = {"url": "jobs:claim"}
    url = "http://localhost:8000/jobs/abc:claim"
    requests_mock.post(url, json=resp, status_code=200)
    resp = n.claim_job("abc")
    assert ":claim" in resp["url"]
    assert resp["claimed"] is False

    requests_mock.post(url, json={}, status_code=409)
    resp = n.claim_job("abc")
    assert resp["claimed"] is True

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

def test_nmdc_client_validate(requests_mock, caplog, site_config_file):
    api = nmdcapi(site_config_file)
    valid_json = {
        "data_object_set": [
            {
                "id": "nmdc:dobj-11-rhjsg657",
                "name": "Test Object",
                "description": "valid type",
                "data_category": "processed_data",
                "type": "nmdc:DataObject",
                "data_object_type":"Raw sequencing data read 1"
            }
        ]
    }
    invalid_json = {
        "data_object_set": [
            {
                "id": "nmdc:dobj-11-rhjsg657",
                "name": "Test Object",
                "description": "invalid type",
                "data_category": "processed_data",
                "type": "nmdc:DataObject",
                "data_object_type":"Invalid type"
            }
        ]
    }
    requests_mock.post(
        "https://api.microbiomedata.org/metadata/json:validate",
        [
            {"text": '{"result":"All Okay!"}', "status_code": 200},
            {
                "text": '{"result":"errors","detail":{"data_object_set":["Invalid type"]}}',
                "status_code": 200,
            },
        ],
    )

    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert api.validate_metadata(valid_json) == 200
    assert "Validation passed!" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.INFO), pytest.raises(Exception, match="Validation failed"):
        api.validate_metadata(invalid_json)
    assert "Validation failed." in caplog.text

def test_nmdc_client_submit(requests_mock, caplog, site_config_file):
    api = nmdcapi(site_config_file)
    token_resp = {"expires": {"minutes": 60}, "access_token": "abcd"}
    valid_json = {
        "data_object_set": [
            {
                "id": "nmdc:dobj-11-rhjsg657",
                "name": "Test Object",
                "description": "valid type",
                "data_category": "processed_data",
                "type": "nmdc:DataObject",
                "data_object_type":"Raw sequencing data read 1"
            }
        ]
    }
    invalid_json = {
        "data_object_set": [
            {
                "id": "nmdc:dobj-11-rhjsg657",
                "name": "Test Object",
                "description": "invalid type",
                "data_category": "processed_data",
                "type": "nmdc:DataObject",
                "data_object_type":"Invalid type"
            }
        ]
    }
    requests_mock.post("http://localhost:8000/token", json=token_resp)
    requests_mock.post(
        "https://api.microbiomedata.org/metadata/json:submit",
        [
            {"status_code": 200},
            {
                "text": '{"result":"errors","detail":{"data_object_set":["Invalid type"]}}',
                "status_code": 400,
            },
        ],
    )

    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert api.submit_metadata(valid_json) == 200
    assert "Submission passed!" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.INFO), pytest.raises(Exception, match="Submission failed"):
        api.submit_metadata(invalid_json)
    assert "Request failed" in caplog.text

#### IM HERE: ADD TESTS FOR SUBMIT AND VALIDATE JSONS, BELIEVE CURRENT ASSERTION LOGIC WRONG
# also check which function is teh one that fails with a large allow list due to http length and change to batch api call