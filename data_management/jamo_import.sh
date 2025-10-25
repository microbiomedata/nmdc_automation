#!/bin/bash
# Usage: jamo_import.sh [--dev] <path_to_metadata_dir>

# Example:
# cd /global/cfs/cdirs/m3408/jamo_metadata ;
# jamo_import.sh /global/cfs/cdirs/m3408/jamo_metadata/metadata_files 2>&1 | tee jamo_import.log

# Parse command line arguments
DEV_FLAG=false
METADATA_DIR=""
DATA_CENTER="nersc"
ENVIRONMENT="prod"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="$SCRIPT_DIR/jamo_import.db"

while [[ $# -gt 0 ]]; do
  case $1 in
    --dev)
      DEV_FLAG=true
      ENVIRONMENT="dev"
      shift
      ;;
    *)
      METADATA_DIR="$1"
      shift
      ;;
  esac
done

if [[ -z "$METADATA_DIR" ]]; then
  echo "Error: metadata directory path is required."
  exit 1
fi

if [[ ! -d "$METADATA_DIR" ]]; then
  echo "Error: metadata directory '$METADATA_DIR' does not exist."
  exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "Error: sqlite3 command not found."
  exit 1
fi

sqlite_escape() {
  local input="$1"
  input="${input//\'/''}"
  printf "%s" "$input"
}

sqlite3 "$DB_PATH" <<'SQL'
CREATE TABLE IF NOT EXISTS import_history (
  filename TEXT NOT NULL,
  env TEXT NOT NULL,
  update_time TEXT NOT NULL,
  PRIMARY KEY (filename, env)
);
SQL

ENVIRONMENT_SQL="$(sqlite_escape "$ENVIRONMENT")"

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

cd "$METADATA_DIR"

# if dev flag is set run module load jamo/dev
if [ "$DEV_FLAG" = true ]; then
  module load jamo/dev
else
  module load jamo
fi

# TODO: check for workflow_execution record in jamo
for file in metadata*.json; do
  if [[ ! -e "$file" ]]; then
    continue
  fi

  wf_key=$(echo "$file" | cut -d':' -f3 | cut -d'-' -f1)
  workflow="${wf_dict[$wf_key]}"
  if [[ -z "$workflow" ]]; then
    echo "Warning: Unable to determine workflow for $file; skipping."
    continue
  fi

  file_sql="$(sqlite_escape "$file")"
  already_imported=$(sqlite3 "$DB_PATH" "SELECT 1 FROM import_history WHERE filename = '$file_sql' AND env = '$ENVIRONMENT_SQL' LIMIT 1;")
  if [[ "$already_imported" == "1" ]]; then
    echo "Skipping $file; already imported for $ENVIRONMENT."
    continue
  fi

  if [ "$DEV_FLAG" = true ]; then
    echo jat import "dev/$workflow" "$file" "$DATA_CENTER"
  else
    echo jat import "$workflow" "$file" "$DATA_CENTER"
  fi

  if [ $? -eq 0 ]; then
    # mv "$file" "${file}.done"
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    sqlite3 "$DB_PATH" "INSERT INTO import_history (filename, env, update_time) VALUES ('$file_sql', '$ENVIRONMENT_SQL', '$timestamp') ON CONFLICT(filename, env) DO UPDATE SET update_time=excluded.update_time;"
    echo "Imported $file"
  else
    echo "Error: Failed to import $file"
  fi
done
