Onboarding:

I've updated the documentation some amount over the past year, but I've started another PR for anything that comes up when chatting with you. We'll mostly be going over things that are in the main readme, but even that I've made small changes on my branch. Feel free to check both out or just the diff view on the PR.
I'm sure Alicia mentioned already, but things you'll need to get set up before you're able to run anything are as follows:
perlmutter access as your personal user and as nmdcda, ideally with use of the [sshproxy script](https://docs.nersc.gov/connect/mfa/#sshproxy)
access to SPIN / rancher (may need a [training](https://docs.nersc.gov/services/spin/#get-started) if you haven't done it already)
access to the dev and prod [mongodb](https://docs.google.com/document/d/11h21epiEX2HVM8pUNYPw8dzx_9p0Rx8BkpHcDk62Utc/edit?tab=t.0#heading=h.qyxkoy9mt63k) and runtime api
lowest priority is a [JAWS token](https://jaws-docs.jgi.doe.gov/en/latest/jaws/jaws_config.html), since we don't expect you to do a lot of trouble shooting from the get-go.

Typical error on scheduler that means the watcher or perlmutter has come down:
<details>

```bash
Traceback (most recent call last):
  File "/usr/local/lib/python3.11/site-packages/urllib3/connectionpool.py", line 787, in urlopen
    response = self._make_request(
               ^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/urllib3/connectionpool.py", line 534, in _make_request
    response = conn.getresponse()
               ^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/urllib3/connection.py", line 571, in getresponse
    httplib_response = super().getresponse()
                       ^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/http/client.py", line 1395, in getresponse
    response.begin()
  File "/usr/local/lib/python3.11/http/client.py", line 325, in begin
    version, status, reason = self._read_status()
                              ^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/http/client.py", line 294, in _read_status
    raise RemoteDisconnected("Remote end closed connection without"
http.client.RemoteDisconnected: Remote end closed connection without response

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/usr/local/lib/python3.11/site-packages/requests/adapters.py", line 644, in send
    resp = conn.urlopen(
           ^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/urllib3/connectionpool.py", line 841, in urlopen
    retries = retries.increment(
              ^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/urllib3/util/retry.py", line 474, in increment
    raise reraise(type(error), error, _stacktrace)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/urllib3/util/util.py", line 38, in reraise
    raise value.with_traceback(tb)
  File "/usr/local/lib/python3.11/site-packages/urllib3/connectionpool.py", line 787, in urlopen
    response = self._make_request(
               ^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/urllib3/connectionpool.py", line 534, in _make_request
    response = conn.getresponse()
               ^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/urllib3/connection.py", line 571, in getresponse
    httplib_response = super().getresponse()
                       ^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/http/client.py", line 1395, in getresponse
    response.begin()
  File "/usr/local/lib/python3.11/http/client.py", line 325, in begin
    version, status, reason = self._read_status()
                              ^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/http/client.py", line 294, in _read_status
    raise RemoteDisconnected("Remote end closed connection without"
urllib3.exceptions.ProtocolError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/src/nmdc_automation/workflow_automation/sched.py", line 413, in <module>
    main(site_conf=sys.argv[1], wf_file=sys.argv[2])
  File "/src/nmdc_automation/workflow_automation/sched.py", line 402, in main
    sched.cycle(dryrun=dryrun, skiplist=skiplist, allowlist=allowlist)
  File "/src/nmdc_automation/workflow_automation/sched.py", line 316, in cycle
    wfp_nodes = load_workflow_process_nodes(self.api, self.workflows, allowlist)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/src/nmdc_automation/workflow_automation/workflow_process.py", line 340, in load_workflow_process_nodes
    data_object_map = get_required_data_objects_map(nmdcapi, workflows)
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/src/nmdc_automation/workflow_automation/workflow_process.py", line 28, in get_required_data_objects_map
    records = api.list_from_collection("data_object_set", q)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/src/nmdc_automation/api/nmdcapi.py", line 262, in list_from_collection
    resp = requests.get(url, headers=self.header, params=params).json()
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/requests/api.py", line 73, in get
    return request("get", url, params=params, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/requests/api.py", line 59, in request
    return session.request(method=method, url=url, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/requests/sessions.py", line 589, in request
    resp = self.send(prep, **send_kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/requests/sessions.py", line 703, in send
    r = adapter.send(request, **kwargs)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/local/lib/python3.11/site-packages/requests/adapters.py", line 659, in send
    raise ConnectionError(err, request=request)
requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
```
</details>


Report should allow for submitting multiple study IDs, and for each ID, to generate a table of wfe vs job wfes with counts. output with dates for tracking between dates. 

To check on a workflow process, you can use this aggregation in mongodb:

<details>

```javascript
[
  {
    $match: {
      associated_studies: "nmdc:sty-11-hht5sb92",
      analyte_category: "metagenome"
    }
  },
  {
    $lookup: {
      from: "data_object_set",
      localField: "has_output",
      foreignField: "id",
      as: "data_object_set"
    }
  },
  {
    $lookup: {
      from: "workflow_execution_set",
      localField: "id",
      foreignField: "was_informed_by",
      pipeline: [
        {
          $sort: {
            type: 1
          }
        }
      ],
      as: "workflow_execution_set"
    }
  },
  {
    $lookup: {
      from: "jobs",
      localField: "id",
      foreignField: "config.was_informed_by",
      pipeline: [
        {
          $sort: {
            "config.activity.type": 1
          }
        }
      ],
      as: "jobs"
    }
  },
  {
    $match: {
      $or: [
        {
          $expr: {
            $lt: [
              {
                $size: "$workflow_execution_set"
              },
              5
            ]
          }
        },
        {
          workflow_execution_set: {
            $not: {
              $elemMatch: {
                type: "nmdc:MagsAnalysis"
              }
            }
          }
        }
      ]
    }
  },
  // {
  //   $match: {
  //     workflow_execution_set: {
  //       $not: {
  //         $elemMatch: {
  //           type: "nmdc:MagsAnalysis"
  //         }
  //       }
  //     }
  //   }
  // }
  {
    $match: {
      "data_object_set.in_manifest": {
        $exists: false
      },
      "workflow_execution_set.qc_status": {
        $exists: false
      },
      "workflow_execution_set.qc_comment": {
        $exists: false
      },
      has_output: {
        $exists: true
      }
    }
  },
  {
    $group: {
      _id: {
        wfex_type: "$workflow_execution_set.type",
        job_wfex_type:
          "$jobs.config.activity.type"
      },
      executions: {
        $push: {
          id: "$id",
          wfex_id: "$workflow_execution_set.id",
          wfex_end:
            "$workflow_execution_set.ended_at_time",
          job_id: "$jobs.id",
          job_wfid: "$jobs.config.activity_id",
          job_start: "$jobs.created_at"
        }
      }
    }
  }
]
```

</details>

It returns groups of data generation set IDs based off what workflows they have in the workflow execution set (aka the done and good ones) versus the jobs collection (aka it has run, but may have errored at some point if it isn't also in the workflow execution set).

currently, there's a python script that can generate a report from the nersc prod env:

```
python nmdc_automation/run_process/run_report.py study-report ../site_configuration_nersc_prod.toml nmdc:sty-11-hht5sb92
```

It outputs something like this:
```
2026-01-25 16:11:33,516 INFO: Generating report for study nmdc:sty-11-hht5sb92 from ../site_configuration_nersc_prod.toml
2026-01-25 16:11:34,353 INFO: Found 185 Un-pooled Data Generation IDs
2026-01-25 16:11:53,440 INFO: Workflow status found: {
  "Done": 102,
  "Not done": 83
}
2026-01-25 16:11:53,441 INFO: 83 Data generations not done:
nmdc:omprc-12-6a2d5s20
nmdc:dgns-11-v88j5a32
...
```
But there are actually 110 not done, because there are 28 that failed rbt but passed MAGs that it doesn't take into account. 