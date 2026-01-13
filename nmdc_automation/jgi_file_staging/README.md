## Table of Contents
- [Table of Contents](#table-of-contents)
  - [JGI Data Staging](#jgi-data-staging)
    - [SOP](#sop)
    - [POC](#poc)


### JGI Data Staging

1. create project in mongodb
   1. jgi_file_metadata.py <project_name> site_configuration.toml -i -p project_config.toml
2. jgi_file_metadata.py 
   1. Get sample metadata from JGI and enter into mongodb 
3. file_restoration.py 
   1. Restore files from tape
   2. repeat until all files restored
   3. Monitor restore requests until they are fulfilled
4. globus_file_transfer.py
   1. Get Globus manifests for restored files
   2. Create and submit Globus batch file
   3. Monitor Globus transfers until complete
5. staged_files.py
   1. Verify files have been staged correctly
6. mapping_tsv.py
   1. Create mapping tsv files for metaG and metaT sample directories

Config file contains parameters that can change, such as Globus id, 
notification email, file destination, etc.

Mongodb is used to track the metadata and the status of the files.

#### SOP
1. Get offline token https://gold-ws.jgi.doe.gov/
2. Set options in site_configuration.toml, staging_configuration.toml and project_config.toml
3. Activate pipenv
5. Get proposal_id for project from gold.jgi.doe.gov
6. Run jgi_file_metadata.py with config tomls, the proposal ID and the project name
7. Get JDP_TOKEN
   1. login to https://data.jgi.doe.gov/
   2. Click on profile icon in upper right corner and select 'Copy My Session Token'
8. Run file_restoration.py with project name and config tomls to restore files from tape
   1. 750 samples per request
   2. maximum of 10TB can be requested every 24 hours
   3. run every 24 hours until all files have been requested
9. Run globus_file_transfer.py after files have been restored from tape with config tomls and project name
   1. call with '--request_id' to get the Globus manifest file
   2. If running from local machine:
      1. copy Globus manifest file to local machine
      2. update nersc_manifests_directory to directory with manifest files
   3. call without any optional arguments to create and submit Globus batch files to perform Globus transfers
10. use staged_files.py to verify that all of the files that need to be staged exist on NERSC
11. create mapping tsv files using mapping_tsv.py
   1. <project_name>.<ap_type>.map.tsv where <ap_type> in {metag, metat}


#### POC
- Mark Flynn <mflynn@lanl.gov>