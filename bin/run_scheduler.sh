#!/bin/bash
set -euo pipefail

# Default values
WORKSPACE="dev"
YAML="/src/nmdc_automation/config/workflows/workflows.yaml"
LIST="/conf/allow.lst"
TOML="/conf/site_configuration.toml"
PORT="27017"
PID_FILE="/conf/sched.pid"
LOG_FILE="/conf/sched.log"
FULL_LOG_FILE="/conf/sched_full.log"
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/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"
ERROR_ALERTED_FILE="/conf/scheduler_error_alerted_$WORKSPACE"

DEBUG=0
CLEANED_UP=0
RESTARTING=0
SCRIPT_NAME=$(basename "$0")
MY_PID=$$
TAIL_PID=

# Help message
show_help() {
  echo "Usage: ./run_scheduler.sh [--yaml PATH] [--allowlist PATH] [--toml PATH] [--port PORT]"
  echo
  echo "Options:"
  echo "  -y, --yaml PATH        Path to workflow YAML file (default: $YAML)"
  echo "  -a, --allowlist PATH   Path to allowlist file     (default: $LIST)"
  echo "  -t, --toml PATH        Path to site config TOML   (default: $TOML)"
  echo "  -p, --port PORT        MongoDB port number        (default: $PORT)"
  echo "  -d, --debug            Enable debug mode (outputs to stdout)"
  echo "  -h, --help             Show this help message"
}

send_slack_notification() {
  local message="$1"
  curl -s -X POST -H 'Content-type: application/json' \
    --data "{\"text\": \"$message\"}" \
    "$SLACK_WEBHOOK_URL" > /dev/null
  # echo "[Slack] Sent message: $message | Response: $RESPONSE" >> "$LOG_FILE"
}

# Cleanup old scheduler and related processes before starting new
cleanup_old() {
  echo "Cleaning up old scheduler and monitor processes..." > "$LOG_FILE"
  DUPLICATES=$(pgrep -f "$SCRIPT_NAME" | grep -v "^$MY_PID\$" || true)
  if [[ -n "$DUPLICATES" ]]; then
    echo "[INFO] Found duplicate scheduler PIDs: $DUPLICATES" >> "$LOG_FILE"
    echo "$DUPLICATES" | xargs kill
  fi

  pkill -f "tail -F /conf/sched.log" || true
  pkill -f "grep --line-buffered --ignore-case error" || true

  rm -f "$PID_FILE"
}


cleanup() {
  if [[ $CLEANED_UP -eq 1 ]]; then return; fi
  CLEANED_UP=1
  if [[ $RESTARTING -eq 0 ]]; then
    END_TIME=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
    send_slack_notification ":x: *Scheduler-$WORKSPACE stopped* at \`$END_TIME\`"
    echo "[$END_TIME] Watcher script terminated" | tee -a "$LOG_FILE" "$FULL_LOG_FILE" > /dev/null
  fi
  if [[ -n "${TAIL_PID:-}" ]]; then
    kill "$TAIL_PID" 2>/dev/null || true
  fi
  if [[ -f "$ERROR_ALERTED_FILE" && $RESTARTING -eq 0 ]]; then
    rm -f "$ERROR_ALERTED_FILE"
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
    -d|--debug)
      DEBUG=1
      shift
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

# Before starting, clean up old instances and helpers
cleanup_old

# Export and execute
export MONGO_PORT="$PORT"
export NMDC_WORKFLOW_YAML_FILE="$YAML"
export NMDC_SITE_CONF="$TOML"

# Kill existing scheduler process if running
if [[ -f "$PID_FILE" ]]; then
  OLD_PID=$(cat "$PID_FILE")
  if ps -p "$OLD_PID" > /dev/null 2>&1; then
    PROC_CMD=$(ps -p "$OLD_PID" -o args= | tr -d '\n' | sed 's/[[:space:]]*$//')
    echo "Found running process $OLD_PID: $PROC_CMD" | tee -a "$LOG_FILE" > /dev/null
    if [[ "$PROC_CMD" == *"workflow_automation.sched"* ]]; then
      kill "$OLD_PID" 2>/dev/null
      KILL_TIME=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
      echo "Killed existing scheduler PID $OLD_PID" | tee -a "$LOG_FILE" > /dev/null
      RESTARTING=1
      send_slack_notification ":arrows_counterclockwise: *Scheduler-$WORKSPACE refreshed* at \`$KILL_TIME\` (previous PID: $OLD_PID)"
    else
      echo "PID $OLD_PID is not the scheduler, skipping kill" | tee -a "$LOG_FILE" > /dev/null
    fi
  else
    echo "PID $OLD_PID not running" | tee -a "$LOG_FILE" > /dev/null
  fi
fi

cd /src || exit 1

START_TIME=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
send_slack_notification ":rocket: *Scheduler-$WORKSPACE started* at \`$START_TIME\`"
echo "[$START_TIME] Scheduler script started" | tee "$LOG_FILE" -a "$FULL_LOG_FILE" > /dev/null

# Start error log monitoring — silent and tracked via TAIL_PID
rm -f "$ERROR_ALERTED_FILE"
{
  tail -F "$LOG_FILE" 2>/dev/null &
  TAIL_PID=$!
  wait $TAIL_PID
} | grep --line-buffered --ignore-case 'error' | while read -r line; do
  if [[ ! -f "$ERROR_ALERTED_FILE" ]]; then
    TIMESTAMP=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
    send_slack_notification ":warning: *Scheduler-$WORKSPACE ERROR* at \`$TIMESTAMP\`:\n\`\`\`$line\`\`\`"
    touch "$ERROR_ALERTED_FILE"
  fi
done > /dev/null &

(
  # Run the Python script
  if [[ "$DEBUG" -eq 1 ]]; then
    # sleep 60
    ALLOWLISTFILE="$LIST" python -m nmdc_automation.workflow_automation.sched \
      "$NMDC_SITE_CONF" \
      "$NMDC_WORKFLOW_YAML_FILE" 2>&1 | tee "$LOG_FILE" -a "$FULL_LOG_FILE" &
  else
    # sleep 60
    ALLOWLISTFILE="$LIST" python -m nmdc_automation.workflow_automation.sched \
      "$NMDC_SITE_CONF" \
      "$NMDC_WORKFLOW_YAML_FILE" 2>&1 | tee -a "$LOG_FILE" "$FULL_LOG_FILE" > /dev/null
  fi

  # Save the PID
  SCHED_PID=$!
  echo "$SCHED_PID" > "$PID_FILE"
  wait $SCHED_PID
) & disown