#!/bin/bash
set -euo pipefail

# Default values
WORKSPACE="dev"
LIST="/conf/allow.lst"
TOML="/conf/site_configuration.toml"
PORT="27017"
PID_FILE="/conf/test.sched.pid"
LOG_FILE="/conf/test.sched.log"
FULL_LOG_FILE="/conf/test.sched_full.log"
ERROR_ALERTED_FILE="/conf/err_alert_$WORKSPACE"
SCRIPT_NAME=$(basename "$0")
SLACK_WEBHOOK_URL=$(grep 'slack_webhook' "$TOML" | sed 's/.*= *"\(.*\)"/\1/')
YAML=$(grep 'workflows_config' "$TOML" | sed 's/.*= *"\(.*\)"/\1/')

DEBUG=0
CLEANED_UP=0
RESTARTING=0
MISMATCH=0
HELP=0
SH_PID=$$
SCHED_PID=""
TAIL_PID=""
OLD_PID=""
KILL_PID=""
LAST_ALERT=""
LAST_ERROR=""
LOG_START_SIZE=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)

# ---------------------
# Help message
# ---------------------
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
  HELP=1
}

# ---------------------
# Send Slack notification
# ---------------------
send_slack_notification() {
  local message="$1"
  curl -s -X POST -H 'Content-type: application/json' \
    --data "{\"text\": \"$message\"}" \
    "$SLACK_WEBHOOK_URL" > /dev/null
}

# ---------------------
# Debug message logging
# ---------------------
log() {
    local message="$1"
    if [[ "$DEBUG" -eq 1 ]]; then
        echo "$message" | tee -a "$LOG_FILE" "$FULL_LOG_FILE"
    else
        echo "$message" >> "$LOG_FILE"
        echo "$message" >> "$FULL_LOG_FILE"
    fi
}


# ---------------------
# Cleanup old scheduler and related processes
# ---------------------
cleanup_old() {
  rm -f "$LOG_FILE"
  log "Cleaning up old scheduler and monitor processes..." # > "$LOG_FILE"
  log $(pgrep -af "$SCRIPT_NAME")
  DUPLICATES=$(pgrep -af "$SCRIPT_NAME" | awk -v mypid="$SH_PID" '$1 != mypid {print $1}' || true)
  if [[ -n "$DUPLICATES" ]]; then
    log "[INFO] Found duplicate scheduler PIDs: $DUPLICATES" # >> "$LOG_FILE"
    kill "$DUPLICATES" 2>/dev/null || true
  fi

  pkill -f "tail -F $LOG_FILE" || true
}

# ---------------------
# Cleanup on exit
# ---------------------
cleanup() {
  TIMESTAMP=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
  if [[ $CLEANED_UP -eq 1 ]]; then return; fi
  CLEANED_UP=1

  log "CLEANUP RESTARTING MISMATCH KILL_PID LOG_START_SIZE"
  log $CLEANED_UP $RESTARTING $MISMATCH $KILL_PID $LOG_START_SIZE

  # Always clean up tail process if it exists 
  if [[ -n "${TAIL_PID:-}" ]]; then
    kill "$TAIL_PID" 2>/dev/null || true
  fi

  # If this cleanup was triggered by a restart, kill the old PID
  if [[ $RESTARTING -eq 1 && -n "$KILL_PID" ]]; then
    kill "$KILL_PID" 2>/dev/null
    MSG=":arrows_counterclockwise: *Scheduler-$WORKSPACE script refresh* at \`$TIMESTAMP\` (replacing PID \`$OLD_PID\`)"
    log "[$TIMESTAMP] Scheduler script restarted" #| tee -a "$LOG_FILE"
    send_slack_notification "$MSG"
  fi

  log "CLEANUP RESTARTING MISMATCH KILL_PID"
  log $CLEANED_UP $RESTARTING $MISMATCH $KILL_PID
  # Only send termination message if not restarting and no mismatch
  if [ "$RESTARTING" -eq 1 ] || [ "$MISMATCH" -eq 1 ] || [ "$HELP" -eq 1 ]; then
    :  # no-op, do nothing
  else
    # send_slack_notification ":x: *Scheduler-$WORKSPACE stopped* at \`$TIMESTAMP\`"
    log "[$TIMESTAMP] Scheduler script terminated" #| tee -a "$LOG_FILE" "$FULL_LOG_FILE" > /dev/null
    NEW_LOG_LINES=$(tail -c +$((LOG_START_SIZE + 1)) "$LOG_FILE")
    LAST_ERROR=$(echo "$NEW_LOG_LINES" | grep --ignore-case --extended-regexp 'error|exception' | tail -n 1)
    log "LAST_ERROR: $LAST_ERROR"
    log "LAST_ALERT: $LAST_ALERT"
    # If there was an error and it's not the same as the last alert, send a notification
    if [[ -n "$LAST_ERROR" && "$LAST_ERROR" != "$LAST_ALERT" ]]; then
      send_slack_notification ":x: *Scheduler-$WORKSPACE script terminated* at \`$TIMESTAMP\`.\nLatest error:\n\`\`\`$LAST_ERROR\`\`\`"
    else
      send_slack_notification ":x: *Scheduler-$WORKSPACE script terminated* at \`$TIMESTAMP\`"
    fi
    log "CLEANUP RESTARTING MISMATCH KILL_PID"
    log $CLEANED_UP $RESTARTING $MISMATCH $KILL_PID
    exit 0
  fi
}
trap cleanup SIGINT SIGTERM EXIT

# ---------------------
# Parse arguments
# ---------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yaml)      YAML="$2"; shift 2 ;;
    -a|--allowlist) LIST="$2"; shift 2 ;;
    -t|--toml)      TOML="$2"; shift 2 ;;
    -p|--port)      PORT="$2"; shift 2 ;;
    -d|--debug)     DEBUG=1; shift ;;
    -h|--help)      show_help; exit 0 ;;
    *)              echo "Unknown option: $1"; show_help; exit 1 ;;
  esac
done

# ---------------------
# Clean up old instances before starting
# ---------------------


# Environment variables for scheduler
export MONGO_PORT="$PORT"
export NMDC_WORKFLOW_YAML_FILE="$YAML"
export NMDC_SITE_CONF="$TOML"

# ---------------------
# Kill existing scheduler if running
# ---------------------

if [[ -f "$PID_FILE" ]] && read -r OLD_PID < "$PID_FILE" && ps -p "$OLD_PID" > /dev/null 2>&1; then
  CMD_NAME=$(ps -p "$OLD_PID" -o args= | tr -d '\n' | sed 's/[[:space:]]*$//')
  log "Found running process $OLD_PID: $CMD_NAME" #| tee -a "$LOG_FILE" > /dev/null
  if [[ "$CMD_NAME" == *python* ]]; then
    PROC_CMD=$(ps -p "$OLD_PID" -o args=)
    if [[ "$PROC_CMD" == *" sched."* ]]; then  # For testing
    # if [[ "$PROC_CMD" == *"workflow_automation.sched"* ]]; then
      RESTARTING=1
      KILL_PID="$OLD_PID"
      cleanup
    else
      log "PID $OLD_PID is not the scheduler, skipping kill" #| tee -a "$LOG_FILE" > /dev/null
      MISMATCH=1
      exit 1
    fi
  else
    log "PID $OLD_PID is not a python process, skipping kill" #| tee -a "$LOG_FILE" > /dev/null
    MISMATCH=1
    exit 1
  fi
else
  log "PID $OLD_PID not running" #| tee -a "$LOG_FILE" > /dev/null
fi




# ---------------------
# Error log monitoring
# ---------------------
# rm -f "$ERROR_ALERTED_FILE"

# monitor_errors() {
tail -F "$LOG_FILE" \
  | grep --line-buffered --ignore-case --extended-regexp 'error|exception' \
  | while read -r line; do
    log "Starting monitoring"
    if [[ ! -f "$ERROR_ALERTED_FILE" ]]; then
      TIMESTAMP=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
      send_slack_notification ":warning: *Scheduler-$WORKSPACE ERROR* at \`$TIMESTAMP\`:\n\`\`\`$line\`\`\`"
      touch "$ERROR_ALERTED_FILE"
      log "[$TIMESTAMP] - $ERROR_ALERTED_FILE created" 
      LAST_ALERT="$line"
    fi
done &
TAIL_PID=$!
# }

# if [[ "$DEBUG" -eq 0 ]]; then
#   log "Starting er_ror monitoring in background..."
#   monitor_errors > /dev/null &
# else
#   log "Debug mode enabled, starting er_ror monitoring in foreground..."
#   monitor_errors
# fi


# ---------------------
# Start scheduler
# ---------------------
# cd /src || exit 1 #commented for testing

START_TIME=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
send_slack_notification ":rocket: *Scheduler-$WORKSPACE started* at \`$START_TIME\`"
log "[$START_TIME] Scheduler script started" #| tee -a "$LOG_FILE" "$FULL_LOG_FILE" > /dev/null

RESTARTING=0

# ---------------------
# Launch Python scheduler
# ---------------------
(
  if [[ "$DEBUG" -eq 1 ]]; then
    log "Debug mode enabled."
    python sched.py 2>&1 | tee -a "$LOG_FILE" "$FULL_LOG_FILE" 
    export NMDC_LOG_LEVEL=DEBUG
    # ALLOWLISTFILE="$LIST" python -m nmdc_automation.workflow_automation.sched \
    #   "$NMDC_SITE_CONF" \
    #   "$NMDC_WORKFLOW_YAML_FILE" 2>&1 | tee -a "$LOG_FILE" "$FULL_LOG_FILE" 
    SCHED_PID=$!
  else
    python sched.py 2>&1 | tee -a "$LOG_FILE" "$FULL_LOG_FILE" > /dev/null &
    # ALLOWLISTFILE="$LIST" python -m nmdc_automation.workflow_automation.sched \
    #   "$NMDC_SITE_CONF" \
    #   "$NMDC_WORKFLOW_YAML_FILE" 2>&1 | tee -a "$LOG_FILE" "$FULL_LOG_FILE" > /dev/null &
    SCHED_PID=$!
    # echo "$SCHED_PID" > "$PID_FILE"
    # wait $SCHED_PID
  fi

  # Save PID and wait for process
  echo "$SCHED_PID" > "$PID_FILE"
  wait $SCHED_PID
) & disown
# sleep 10


# run_scheduler() {
#   if [[ "$DEBUG" -eq 1 ]]; then
#     log "Debug mode enabled."
#     export NMDC_LOG_LEVEL=DEBUG
#     python sched.py 2>&1 | tee -a "$LOG_FILE" "$FULL_LOG_FILE"
#   else
#     python sched.py 2>&1 | tee -a "$LOG_FILE" "$FULL_LOG_FILE" > /dev/null &
#   fi
# }

# run_scheduler
# SCHED_PID=$!
# echo "$SCHED_PID" > "$PID_FILE"


# if [[ "$DEBUG" -eq 1 ]]; then
#   log "Debug mode enabled."
#   export NMDC_LOG_LEVEL=DEBUG
#   # Run in foreground so you can see output
#   python sched.py 2>&1 | tee -a "$LOG_FILE" "$FULL_LOG_FILE"
#   SCHED_PID=$!  # Not strictly needed here since it's foreground
# else
#   # Run in background
#   python sched.py 2>&1 | tee -a "$LOG_FILE" "$FULL_LOG_FILE" > /dev/null &
#   SCHED_PID=$!
# fi

# Save PID to file
# log "Saving scheduler PID $SCHED_PID to $PID_FILE"
# echo "$SCHED_PID" > "$PID_FILE"
# wait $SCHED_PID

# # Wait for the scheduler if it's running in background
# if [[ "$DEBUG" -eq 0 ]]; then
#   wait $SCHED_PID
# fi