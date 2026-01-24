#!/bin/bash
set -euo pipefail

WORKSPACE="dev"
LIST="/conf/allow.lst"
TOML="/conf/site_configuration.toml"
PORT="27017"
PID_FILE="/conf/test.sched.pid"
LOG_FILE="/conf/test.sched.log"
FULL_LOG_FILE="/conf/test.sched_full.log"
ERROR_ALERTED_FILE="/tmp/err_alert_$WORKSPACE"
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

send_slack_notification() {
    local message="$1"
    curl -s -X POST -H 'Content-type: application/json' \
         --data "{\"text\": \"$message\"}" \
         "$SLACK_WEBHOOK_URL" > /dev/null
}


log() {
    local message="$1"
    if [[ "$DEBUG" -eq 1 ]]; then
        echo "$message" | tee -a "$LOG_FILE" "$FULL_LOG_FILE"
    else
        echo "$message" >> "$LOG_FILE"
        echo "$message" >> "$FULL_LOG_FILE"
    fi
}

cleanup_old() {
  log "$SH_PID"
  pkill -f "tail -F $LOG_FILE" || true
  rm -f "$LOG_FILE" "$ERROR_ALERTED_FILE"
  log "Cleaning up old scheduler and monitor processes..." 
  ALL_MATCHES=$(pgrep -af "$SCRIPT_NAME" || true)
  log "$ALL_MATCHES"
  DUPLICATES=$( echo "$ALL_MATCHES" | awk -v mypid="$SH_PID" '$1 != mypid {print $1}' || true)
  SH_AGE=$(ps -o etimes= -p "$SH_PID" | awk '{print $1}')
  if [[ -n "$DUPLICATES" ]]; then
    log "[INFO] Found duplicate scheduler PIDs: $DUPLICATES"
    for pid in $DUPLICATES; do 
      DUP_AGE=$(ps -o etimes= -p "$pid" 2>/dev/null | awk '{print $1}' || echo 0)
      if [[ "$DUP_AGE" -gt "$SH_AGE" ]]; then
        log "[INFO] Killing duplicate scheduler PID $pid (age: $DUP_AGE seconds)"
        # kill "$pid" 2>/dev/null || true
        RESTARTING=1; KILL_PID="$pid"; cleanup; CLEANED_UP=0
      fi
    done
  fi

}

cleanup() {
  TIMESTAMP=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
  if [[ $CLEANED_UP -eq 1 ]]; then return; fi
  CLEANED_UP=1

  log "CLEANED_UP RESTARTING MISMATCH KILL_PID" 
  log $CLEANED_UP $RESTARTING $MISMATCH $KILL_PID 

  if [[ -n "${TAIL_PID:-}" ]]; then
    kill "$TAIL_PID" 2>/dev/null || true 
    pkill -P "$TAIL_PID" 2>/dev/null || true
  fi

  if [[ $RESTARTING -eq 1 && -n "$KILL_PID" ]]; then
    kill "$KILL_PID" 2>/dev/null
    MSG=":arrows_counterclockwise: *Scheduler-$WORKSPACE script refresh* at \`$TIMESTAMP\` (replacing PID \`$OLD_PID\`)"
    log "[$TIMESTAMP] Scheduler script restarted" 
    send_slack_notification "$MSG"
    log "CLEANED_UP RESTARTING MISMATCH KILL_PID" 
    log $CLEANED_UP $RESTARTING $MISMATCH $KILL_PID 
  fi

  log "CLEANED_UP RESTARTING MISMATCH KILL_PID"
  log $CLEANED_UP $RESTARTING $MISMATCH $KILL_PID
  if [ "$RESTARTING" -eq 1 ] || [ "$MISMATCH" -eq 1 ] || [ "$HELP" -eq 1 ]; then
    :  
  else
    log "[$TIMESTAMP] Scheduler script terminated" 
    send_slack_notification ":x: *Scheduler-$WORKSPACE script terminated* at \`$TIMESTAMP\`"
    if [[ -f "$ERROR_ALERTED_FILE" ]]; then
      LAST_ERROR=$(grep --ignore-case --extended-regexp 'error|exception' $LOG_FILE | tail -n 1)
      LAST_ALERT=$(tail -n1 "$ERROR_ALERTED_FILE")
      log "LAST_ERR: $LAST_ERROR"
      log "LAST_ALERT: $LAST_ALERT"
      if [[ -n "$LAST_ERROR" && "$LAST_ERROR" != "$LAST_ALERT" ]]; then
        send_slack_notification "Latest error:\n\`\`\`$LAST_ERROR\`\`\`"
        # send_slack_notification ":x: *Scheduler-$WORKSPACE script terminated* at \`$TIMESTAMP\`.\nLatest error:\n\`\`\`$LAST_ERROR\`\`\`"
        log "[$TIMESTAMP] Scheduler script terminated with new err_or: $LAST_ERROR"
      fi
    fi
    log "CLEANED_UP RESTARTING MISMATCH KILL_PID"
    log $CLEANED_UP $RESTARTING $MISMATCH $KILL_PID
    exit 0
  fi
}
trap cleanup SIGINT SIGTERM EXIT

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

cleanup_old
export MONGO_PORT="$PORT"
export NMDC_WORKFLOW_YAML_FILE="$YAML"
export NMDC_SITE_CONF="$TOML"

if [[ -f "$PID_FILE" ]] && read -r OLD_PID < "$PID_FILE" && ps -p "$OLD_PID" > /dev/null 2>&1; then
  CMD_NAME=$(ps -p "$OLD_PID" -o args= | tr -d '\n' | sed 's/[[:space:]]*$//')
  log "Found running process $OLD_PID: $CMD_NAME" 
  if ps -p "$OLD_PID" -o args= | grep -qE 'python(.*/)?sched\.py'; then
    RESTARTING=1; KILL_PID="$OLD_PID"; cleanup; CLEANED_UP=0
  else
    log "PID $OLD_PID is not the scheduler, skipping kill" 
    MISMATCH=1; RESTARTING=0
    exit 1
  fi
else
  log "PID $OLD_PID not running" 
fi

log "Starting monitoring"
while read -r line; do
  if [[ ! -f "$ERROR_ALERTED_FILE" ]]; then
    TIMESTAMP=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
    send_slack_notification ":warning: *Scheduler-$WORKSPACE ERROR* at \`$TIMESTAMP\` \n\`\`\`$line\`\`\`"
    # : > "$ERROR_ALERTED_FILE"
    echo "$line" > "$ERROR_ALERTED_FILE"
    LAST_ALERT="$line"
    log "[$TIMESTAMP] - $ERROR_ALERTED_FILE created"
  fi
done < <(tail -F "$LOG_FILE" | stdbuf -oL -eL grep -Ei 'error|exception') &
TAIL_PID=$!

START_TIME=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
send_slack_notification ":rocket: *Scheduler-$WORKSPACE started* at \`$START_TIME\`"
log "[$START_TIME] Scheduler script started" 

RESTARTING=0
CLEANED_UP=0

(
  if [[ "$DEBUG" -eq 1 ]]; then
    log "Debug mode enabled."
    export NMDC_LOG_LEVEL=DEBUG
  fi

  PIPE=$(mktemp -u /tmp/sched.$$.pipe.XXXXX); mkfifo "$PIPE"
  tee -a "$LOG_FILE" "$FULL_LOG_FILE" < "$PIPE" > /dev/null &
  TEE_PID=$!

  python sched.py > "$PIPE" 2>&1 &
  SCHED_PID=$!

  echo "$SCHED_PID" > "$PID_FILE"
  wait "$SCHED_PID"
  rm -f "$PIPE"
) &
LAUNCH_PID=$!
