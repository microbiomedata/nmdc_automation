#!/bin/bash
# Usage: jamo_import.sh [--dev] <path_to_metadata_dir>

# Example:
# cd /global/cfs/cdirs/m3408/jamo_metadata ;
# jamo_import.sh /global/cfs/cdirs/m3408/jamo_metadata/metadata_files 2>&1 | tee jamo_import.log

# Parse command line arguments
DEV_FLAG=false
METADATA_DIR=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --dev)
      DEV_FLAG=true
      shift
      ;;
    *)
      METADATA_DIR="$1"
      shift
      ;;
  esac
done

declare -A wf_dict=(
  ["wfmag"]="nmdc_mags_analysis"
  ["wfmgan"]="nmdc_metagenome_annotation"
  ["wfmgas"]="nmdc_metagenome_assembly"
  ["wfrbt"]="nmdc_read_based_taxonomy_analysis"
  ["wfrqc"]="nmdc_readqc_analysis"
  ["wfmb"]="nmdc_metabolomics_analysis"
  ["wfnom"]="nmdc_nom_analysis"
  ["wfmp"]="nmdc_metaproteomics_analysis"
)

cd $METADATA_DIR

# if dev flag is set run module load jamo/dev
if [ "$DEV_FLAG" = true ]; then
  module load jamo/dev
else
  module load jamo
fi

# TODO: check for workflow_execution record in jamo
for file in metadata*.json; do
  wf=$(echo "$file" | cut -d':' -f3 | cut -d'-' -f1)
  # if dev flag is set run use dev/${wf_dict[$wf]}
  if [ "$DEV_FLAG" = true ]; then
    jat import dev/${wf_dict[$wf]} $file
  else
    jat import ${wf_dict[$wf]} $file
  fi

  if [ $? -eq 0 ]; then
    mv $file ${file}.done
    echo "Imported $file"
  else
    echo "Error: Failed to import $file"
  fi
done
