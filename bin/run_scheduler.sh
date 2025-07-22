#!/bin/bash
set -euo pipefail
# Default values
WORKSPACE="dev"
YAML="/path/to/workflows.yaml"
LIST="/path/to/allow.lst"
TOML="/path/to/site_configuration.toml"
PORT="27017"
PID_FILE="/conf/sched.pid"
LOG_FILE="/conf/sched.log"
FULL_LOG_FILE="/conf/sched_full.log"
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXX"
ERROR_ALERTED_FILE="/conf/scheduler_error_alerted_$WORKSPACE"

CLEANED_UP=0
RESTARTING=0

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

send_slack_notification() {
    local message="$1"
    curl -s -X POST -H 'Content-type: application/json' \
         --data "{\"text\": \"$message\"}" \
         "$SLACK_WEBHOOK_URL" > /dev/null
}

cleanup() {
  if [[ $CLEANED_UP -eq 1 ]]; then return; fi
  CLEANED_UP=1
  if [[ $RESTARTING -eq 0 ]]; then
    END_TIME=$(date)
    send_slack_notification ":stop_sign: *Scheduler-$WORKSPACE stopped* at \`$END_TIME\`"
    echo "[$END_TIME] Watcher script terminated" | tee -a "$LOG_FILE"
  fi
  if [[ -n "${TAIL_PID:-}" ]]; then
    kill "$TAIL_PID" 2>/dev/null
  fi
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

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

# Kill existing scheduler process if running
if [[ -f "$PID_FILE" ]]; then
  OLD_PID=$(cat "$PID_FILE")
  if ps -p "$OLD_PID" > /dev/null 2>&1; then
    kill "$OLD_PID" 2>/dev/null
    KILL_TIME=$(date)
    RESTARTING=1
    send_slack_notification ":arrows_counterclockwise: *Scheduler-$WORKSPACE refreshed* at \`$KILL_TIME\` (previous PID: $OLD_PID)"
  fi
fi

cd /src || exit 1

START_TIME=$(date)
send_slack_notification ":rocket: *Scheduler-$WORKSPACE started* at \`$START_TIME\`"
echo "[$START_TIME] Scheduler script started" | tee -a "$LOG_FILE"

# Start monitoring the log file for errors in background
rm -f "$ERROR_ALERTED_FILE"
tail -F "$LOG_FILE" | grep --line-buffered 'ERROR' | while read -r line; do
    if [[ ! -f "$ERROR_ALERTED_FILE" ]]; then
        TIMESTAMP=$(date)
        send_slack_notification ":warning: *Scheduler-$WORKSPACE ERROR* at \`$TIMESTAMP\`:\n\`\`\`$line\`\`\`"
        touch "$ERROR_ALERTED_FILE"
    fi
done &
TAIL_PID=$!

# Run the Python script
ALLOWLISTFILE="$LIST" python -m nmdc_automation.workflow_automation.sched \
    "$NMDC_SITE_CONF" \
    "$NMDC_WORKFLOW_YAML_FILE" 2>&1 | tee "$LOG_FILE" -a "$FULL_LOG_FILE" &

# Save the PID
SCHED_PID=$!
echo "$SCHED_PID" > "$PID_FILE"
wait $SCHED_PID