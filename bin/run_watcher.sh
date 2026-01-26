#!/bin/bash
set -euo pipefail

# Default values
WORKSPACE="dev"
CONF=/global/homes/n/nmdcda/nmdc_automation/$WORKSPACE/site_configuration_nersc.toml
# prod: CONF=/global/homes/n/nmdcda/nmdc_automation/$WORKSPACE/site_configuration_nersc_$WORKSPACE.toml
HOST=$(hostname)
LOG_FILE=watcher-$WORKSPACE.log
PID_FILE=watcher-$WORKSPACE.pid
HOST_FILE=host-$WORKSPACE.last
SLACK_WEBHOOK_URL=$(grep 'slack_webhook' "$CONF" | sed 's/.*= *"\(.*\)"/\1/')
PVENV=/global/cfs/cdirs/m3408/nmdc_automation/$WORKSPACE/nmdc_automation/.venv

# Global state flags
CLEANED_UP=0
RESTARTING=0
MISMATCH=0
KILL_PID=""
WATCHER_PID=""
OLD_PID=""
OLD_HOST=""
TAIL_PID=""
LAST_ALERT=""
LAST_ERROR=""
IGNORE_PATTERN="Error removing directory /tmp: \[Errno 13\] Permission denied: .*/tmp|['\"]error['\"]:[[:space:]]*['\"][[:space:]]*['\"]"
ALERT_PATTERN='Internal Server Error'
LOG_START_SIZE=$(stat -c%s "$LOG_FILE") 

send_slack_notification() {
    local message="$1"
    curl -s -X POST -H 'Content-type: application/json' \
         --data "{\"text\": \"$message\"}" \
         "$SLACK_WEBHOOK_URL" > /dev/null
}

get_timestamp() {
    echo "$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")"
}

echo_status() {
    echo "CLEANUP RESTARTING MISMATCH KILL_PID"
    echo $CLEANED_UP $RESTARTING $MISMATCH $KILL_PID
}

cleanup() {
    pkill -u "$USER" -f "tail -n 0 -F $LOG_FILE" 2>/dev/null || true
    if [[ $CLEANED_UP -eq 1 ]]; then return; fi
    CLEANED_UP=1

    echo_status

    # Always clean up tail process if it exists    
    if [[ -n "${TAIL_PID:-}" ]]; then
        kill "$TAIL_PID" 2>/dev/null || true 
        pkill -P "$TAIL_PID" 2>/dev/null || true
    fi

    # If this cleanup was triggered by a restart, kill the old PID
    if [[ $RESTARTING -eq 1 && -n "$KILL_PID" ]]; then
        kill "$KILL_PID" 2>/dev/null
        MSG=":arrows_counterclockwise: *Watcher-$WORKSPACE script refresh* on \`$HOST\` at \`$(get_timestamp)\` (replacing PID \`$OLD_PID\`)"
        echo "[$(get_timestamp)] Watcher script restarted" | tee -a "$LOG_FILE"
        send_slack_notification "$MSG"
    fi

    # Only send termination message if not restarting and no mismatch
    if [ "$RESTARTING" -eq 1 ] || [ "$MISMATCH" -eq 1 ]; then
        :  # no-op, do nothing
    else
        EXIT_MESSAGE=":x: *Watcher-$WORKSPACE script terminated* on \`$HOST\` at \`$(get_timestamp)\`"
        if [[ -n "$LAST_ERROR" && "$LAST_ERROR" != "$LAST_ALERT" ]]; then
            EXIT_MESSAGE=":x: *Watcher-$WORKSPACE script terminated* on \`$HOST\` at \`$(get_timestamp)\`.\nLatest error:\n\`\`\`$LAST_ERROR\`\`\`"
        fi
        send_slack_notification "$EXIT_MESSAGE"
        echo "[$(get_timestamp)] Watcher script terminated" | tee -a "$LOG_FILE"
        echo_status
        exit 0
    fi
}
trap cleanup SIGINT SIGTERM EXIT

# Kill existing process only if it's the correct watcher on this host

if [[ -f "$HOST_FILE" ]] && read -r OLD_HOST < "$HOST_FILE" && [[ -n "$OLD_HOST" && "$OLD_HOST" != "$HOST" ]]; then
    echo "Host mismatch: existing watcher was on '$OLD_HOST', current host is '$HOST'. Aborting." | tee -a "$LOG_FILE"
    MISMATCH=1
    exit 1
fi

if [[ "$VIRTUAL_ENV" != "$PVENV" ]]; then
    echo "Incorrect poetry environment. Aborting." | tee -a "$LOG_FILE"
    MISMATCH=1
    exit 1
fi

# Look for an existing watcher process
if [[ -f "$PID_FILE" ]] && read -r OLD_PID < "$PID_FILE" && ps -p "$OLD_PID" > /dev/null 2>&1; then
    CMD_NAME=$(ps -p "$OLD_PID" -o comm=)
    # Check command name (comm) includes 'python'
    if [[ "$CMD_NAME" == *python* ]]; then
        PROC_CMD=$(ps -p "$OLD_PID" -o args=)
        # Check full command line includes 'watcher'
        if [[ "$PROC_CMD" == *"watcher"* ]] && [[ "$OLD_HOST" == "$HOST" ]]; then
            # This is the correct watcher process on the right host
            RESTARTING=1
            KILL_PID="$OLD_PID"
            cleanup
            # sleep 2
        else
            echo "Process command line does not match watcher or host mismatch."
            exit 1
        fi
    else
        echo "Process with PID $OLD_PID is not a python process."
        exit 1
    fi
else
    echo "No active process found for PID $OLD_PID"
fi


send_slack_notification ":rocket: *Watcher-$WORKSPACE started* on \`$HOST\` at \`$(get_timestamp)\`"
echo "[$(get_timestamp)] Watcher script started on $HOST" | tee -a "$LOG_FILE"

# Ensure no leftover tail processes are running for full log file
pkill -u "$USER" -f "tail -n 0 -F $LOG_FILE" 2>/dev/null || true

# Start monitoring the log file for errors in background
tail -n 0 -F "$LOG_FILE" \
  | grep -i --line-buffered -E "error|exception" \
  | grep --line-buffered -v -E "$IGNORE_PATTERN" \
  | while read -r line; do
    LAST_ERROR="$line"
    if [[ "$line" != "$LAST_ALERT" || "$line" == *"$ALERT_PATTERN"* ]]; then
        send_slack_notification ":warning: *Watcher-$WORKSPACE ERROR* on \`$HOST\` at \`$(get_timestamp)\`:\n\`\`\`$line\`\`\`"
        LAST_ALERT="$line"
    fi
done &
TAIL_PID=$!

RESTARTING=0

PYTHONPATH=$(pwd)/nmdc_automation \
    python -m nmdc_automation.run_process.run_workflows watcher --config "$CONF" daemon \
    > >(tee -a "$LOG_FILE") 2>&1 &

WATCHER_PID=$!
echo "$WATCHER_PID" > "$PID_FILE"
echo "$HOST" > "$HOST_FILE"
wait $WATCHER_PID
cleanup