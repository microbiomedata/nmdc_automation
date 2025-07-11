#!/bin/bash

# Default values
YAML="/path/to/workflows.yaml"
LIST="/path/to/allow.lst"
TOML="/path/to/site_configuration.toml"
PORT="27017"

# Help message
show_help() {
  echo "Usage: ./run_scheduler.sh [--yaml PATH] [--allowlist PATH] [--toml PATH] [--port PORT]"
  echo
  echo "Options:"
  echo "  -y, --yaml PATH        Path to workflow YAML file (default: $YAML)"
  echo "  -a, --allowlist PATH   Path to allowlist file     (default: $LIST)"
  echo "  -t, --toml PATH        Path to site config TOML   (default: $TOML)"
  echo "  -p, --port PORT        MongoDB port number        (default: $PORT)"
  echo "  -h, --help             Show this help message"
}

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yaml)
      YAML="$2"
      shift 2
      ;;
    -a|--allowlist)
      LIST="$2"
      shift 2
      ;;
    -t|--toml)
      TOML="$2"
      shift 2
      ;;
    -p|--port)
      PORT="$2"
      shift 2
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      show_help
      exit 1
      ;;
  esac
done

# Export and execute
export MONGO_PORT="$PORT"
export NMDC_WORKFLOW_YAML_FILE="$YAML"
export NMDC_SITE_CONF="$TOML"

# Kill existing scheduler process if PID exists
kill $(cat /conf/sched.pid 2>/dev/null) 2>/dev/null

cd /src

# Run the Python script
ALLOWLISTFILE="$LIST" python -m nmdc_automation.workflow_automation.sched \
    "$NMDC_SITE_CONF" \
    "$NMDC_WORKFLOW_YAML_FILE" > /conf/sched.log 2>&1 &

# Save the PID
jobs -p > /conf/sched.pid