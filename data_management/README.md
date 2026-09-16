# Data Management

This directory contains code for a pipeline to ingest workflow output data into [JAMO](https://jamo.jgi.doe.gov/) for archival.

| File | Description |
| ---- | ----------- |
| `jamo_ingest.py` | Python script that generates metadata files corresponding to the workflow output files and their applicable JAT templates. |
| `jamo_import.sh` | Shell script that executes the actual import for each file. |

## What is JAMO?

JAMO stands for **J**GI (Joint Genome Institute) **A**rchive and **M**etadata **O**rganizer. People on the Berkeley Lab VPN can access the JAMO documentation on the website at [jamo.jgi.doe.gov/doc/JAMO/overview](https://jamo.jgi.doe.gov/doc/JAMO/overview) to learn more.

## What is JAT?

JAT stands for **J**GI **A**nalysis **T**racker. People on the Berkeley Lab VPN can access the JAT documentation (on the JAMO website) at [jamo.jgi.doe.gov/doc/JAT/overview](https://jamo.jgi.doe.gov/doc/JAT/overview) to learn more.

## TODO

- [ ] Document Python package requirements for `jamo_ingest.py` (e.g. add a `requirements.txt` file)
- [ ] Document system requirements for `jamo_import.sh` (e.g. needs an application called `jat` to be present?)
