# Data Management

This directory contains code for a pipeline to ingest workflow output data into [JAMO](https://jamo.jgi.doe.gov/) for archival.

| File | Description |
| ---- | ----------- |
| `jamo_ingest.py` | Generates JSON metadata files (that can be subsequently imported into JAMO) in the `metadata_files/` directory, based upon NMDC workflow execution and data object metadata that either (a) is already cached, or (b) the script fetches from the NMDC API and then caches. |
| `jamo_import.sh` | Imports those JSON metadata files into JAMO, using JAT, and appends `.done` to the name of each successfully imported JSON metadata file. |

## Example usage

The `jamo_import.sh` script is typically run on NERSC Perlmutter, since it requires that the `module load jamo` and `jat` commands are available. The `jamo_ingest.py` script can be run anywhere during testing/development, but is typically run on Perlmutter so the files it generates are conveniently available to the other script.

```sh
# Enter this directory, if not already here.
cd data_management

# Run the Python script in a virtual environment.
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python jamo_ingest.py --clean --generate-labels /path/to/jat/templates

# Run the Bash shell script.
bash jamo_import.sh ./metadata_files
```

## What is JAMO?

JAMO stands for **J**GI (Joint Genome Institute) **A**rchive and **M**etadata **O**rganizer. People on the Berkeley Lab VPN can access the JAMO documentation on the website at [jamo.jgi.doe.gov/doc/JAMO/overview](https://jamo.jgi.doe.gov/doc/JAMO/overview) to learn more.

## What is JAT?

JAT stands for **J**GI **A**nalysis **T**racker. People on the Berkeley Lab VPN can access the JAT documentation (on the JAMO website) at [jamo.jgi.doe.gov/doc/JAT/overview](https://jamo.jgi.doe.gov/doc/JAT/overview) to learn more.

The authoritative source of JAT templates is the `jgi-jat` repository on JGI's GitLab server.
