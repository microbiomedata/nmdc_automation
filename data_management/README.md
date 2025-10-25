# Code for managing NMDC data in JAMO

# Generate metadata files:
```
usage: jamo_ingest.py [-h] [--clean] [--generate-labels TEMPLATE_DIR] [--emsl-only] [--nersc-only]

Run specific methods based on flags

options:
  -h, --help            show this help message and exit
  --clean               Start a clean run with a fresh pull of NMDC data from the runtime api
  --generate-labels TEMPLATE_DIR
                        Generate workflow_labels.json from YAML templates in the specified directory
  --emsl-only           Only process EMSL data records
  --nersc-only          Only process NERSC data records
```

Example:
```
python jamo_ingest.py --clean --generate-labels JAMO_TEMPLATE_DIR 
```


# Push data into JAMO
On perlmutter (run as used nmdcda):
```
cd /global/cfs/cdirs/m3408/jamo_metadata ;
jamo_import.sh /global/cfs/cdirs/m3408/jamo_metadata/metadata_files 2>&1 | tee jamo_import.log
```



# Generate a list of files on the NERSC filesystem

```
jq -r '.[] | .[2] | .[] | .url' valid_data/valid_data.json | grep "data.microbiomedata.org/data" | sed 's|https://data.microbiomedata.org/data/|/global/cfs/cdirs/m3408/results/|g' > nmdc_nersc_dobj.txt
```
