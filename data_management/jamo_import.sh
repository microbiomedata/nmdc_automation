#!/bin/bash
# Usage: jamo_import.sh [--dev] [--dry-run] <path_to_metadata_dir>

# Example:
# cd /global/cfs/cdirs/m3408/jamo_metadata ;
# jamo_import.sh /global/cfs/cdirs/m3408/jamo_metadata/metadata_files 2>&1 | tee jamo_import.log

usage() {
  echo "Usage: $0 [--dev] [--dry-run] <path_to_metadata_dir>"
}

# Parse command line arguments
DEV_FLAG=false
DRY_RUN_FLAG=false
METADATA_DIR=""
DATA_CENTER="nersc"

while [[ $# -gt 0 ]]; do
  case $1 in
    --dev)
      DEV_FLAG=true
      shift
      ;;
    --dry-run)
      DRY_RUN_FLAG=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Error: Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
    *)
      # If we haven't already consumed a CLI argument as the `METADATA_DIR`, consume this one.
      #
      # Note: The reason we bother to check is that a user might accidentally specify multiple
      #       positional arguments and, if we didn't check, we would silently discard earlier
      #       ones here. Checking allows us to avoid that and to show a helpful error message.
      #
      if [[ -n "$METADATA_DIR" ]]; then
        echo "Error: Too many positional arguments." >&2
        usage >&2
        exit 1
      fi
      METADATA_DIR="$1"
      shift
      ;;
  esac
done

# If `$METADATA_DIR` is empty, print an error message and usage string to STDERR, then exit.
if [[ -z "$METADATA_DIR" ]]; then
  echo "Error: Metadata directory path is required." >&2
  usage >&2
  exit 1
fi

declare -A wf_dict=(
  ["wfmag"]="nmdc_mags_analysis"
  ["wfmgan"]="nmdc_metagenome_annotation"
  ["wfmgas"]="nmdc_metagenome_assembly"
  ["wfmtan"]="nmdc_metatranscriptome_annotation"
  ["wfmtas"]="nmdc_metatranscriptome_assembly"
  ["wfmtex"]="nmdc_metatranscriptome_expression_analysis"
  ["wfrbt"]="nmdc_read_based_taxonomy_analysis"
  ["wfrqc"]="nmdc_readqc_analysis"
  ["wfmb"]="nmdc_metabolomics_analysis"
  ["wfnom"]="nmdc_nom_analysis"
  ["wfmp"]="nmdc_metaproteomics_analysis"
)

cd "$METADATA_DIR" || { echo "Error: Failed to cd to $METADATA_DIR"; exit 1; }

# set environment-related vars
if $DEV_FLAG; then
  module_name="jamo/dev"
  template_prefix="dev/"
  env_label="DEV"
else
  module_name="jamo"
  template_prefix=""
  env_label="PROD"
fi

echo "=========================================="
echo "Starting JAMO import at: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Target directory: $METADATA_DIR"
echo "Environment:      $env_label"
$DRY_RUN_FLAG && echo "Mode: DRY RUN (no imports will be executed)"
echo "=========================================="

if ! $DRY_RUN_FLAG; then
  echo "module load $module_name"
  module load $module_name || { echo "Error: 'module load $module_name' failed" >&2; exit 1; }
fi


# Filenames look like: metadata_nmdc:wfmag-11-002wf438.1.json
# Files already imported are renamed to *.done, so they won't match this glob.
shopt -s nullglob
files=(metadata*.json)

if (( ${#files[@]} == 0 )); then
  echo "No metadata*.json files found in $METADATA_DIR. Nothing to do."
  exit 0
fi

# TODO: check for workflow_execution record in jamo; make it skip if found
for file in "${files[@]}"; do
  wf=$(echo "$file" | cut -d':' -f2 | cut -d'-' -f1)
  template="${wf_dict[$wf]}"

  # Check if template not defined
  if [[ -z "$template" ]]; then
    echo "WARNING: Unknown workflow prefix '$wf' in $file; skipping" >&2
    continue
  fi

  cmd=(jat import "${template_prefix}${template}" "$file" "$DATA_CENTER")
  echo "Running: ${cmd[*]}"
  
  if $DRY_RUN_FLAG; then
    continue
  fi

  # using this instead of $? to ensure we check the specific import cmd
  # in case other cmds get added in between
  if "${cmd[@]}"; then
    # Append ".done" to the filename. If that appending fails, print an error message to STDERR.
    mv "$file" "${file}.done" || { echo "Failed to rename file '$file'." >&2; }
    echo "Moved: $file -> ${file}.done"
  else
    echo "Error: Failed to import $file"
  fi
  #echo "------------------------------------------"
done

echo "=========================================="
echo "Script finished at: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
