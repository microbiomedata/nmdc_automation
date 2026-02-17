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
ERROR_ALERTED_FILE="watcher_error_alerted_$WORKSPACE"
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
IGNORE_PATTERN='Error removing directory /tmp: \[Errno 13\] Permission denied: .*/tmp'
ALERT_PATTERN='Internal Server Error'
LOG_START_SIZE=$(stat -c%s "$LOG_FILE") 

send_slack_notification() {
    local message="$1"
    curl -s -X POST -H 'Content-type: application/json' \
         --data "{\"text\": \"$message\"}" \
         "$SLACK_WEBHOOK_URL" > /dev/null
}

cleanup() {
    TIMESTAMP=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
    if [[ $CLEANED_UP -eq 1 ]]; then return; fi
    CLEANED_UP=1

    echo "CLEANUP RESTARTING MISMATCH KILL_PID"
    echo $CLEANED_UP $RESTARTING $MISMATCH $KILL_PID

    pkill -f "tail -F $LOG_FILE" || true

    # Always clean up tail process if it exists    
    if [[ -n "${TAIL_PID:-}" ]]; then
        kill "$TAIL_PID" 2>/dev/null || true 
        pkill -P "$TAIL_PID" 2>/dev/null || true
    fi

    # If this cleanup was triggered by a restart, kill the old PID
    if [[ $RESTARTING -eq 1 && -n "$KILL_PID" ]]; then
        kill "$KILL_PID" 2>/dev/null
        MSG=":arrows_counterclockwise: *Watcher-$WORKSPACE script refresh* on \`$HOST\` at \`$TIMESTAMP\` (replacing PID \`$OLD_PID\`)"
        echo "[$TIMESTAMP] Watcher script restarted" | tee -a "$LOG_FILE"
        send_slack_notification "$MSG"
    fi

    # Only send termination message if not restarting and no mismatch
    if [ "$RESTARTING" -eq 1 ] || [ "$MISMATCH" -eq 1 ]; then
        :  # no-op, do nothing
    else
        EXIT_MESSAGE=":x: *Watcher-$WORKSPACE script terminated* on \`$HOST\` at \`$TIMESTAMP\`"
        NEW_LOG_LINES=$(tail -c +$((LOG_START_SIZE + 1)) "$LOG_FILE")
        LAST_ERROR=$(echo "$NEW_LOG_LINES" | grep -E 'ERROR|Exception' | grep -v "$IGNORE_PATTERN" | tail -n 1)
        echo "CLEANUP RESTARTING MISMATCH KILL_PID"
        echo $CLEANED_UP $RESTARTING $MISMATCH $KILL_PID
        if [[ -n "$LAST_ERROR" && "$LAST_ERROR" != "$LAST_ALERT" ]]; then
            EXIT_MESSAGE=":x: *Watcher-$WORKSPACE script terminated* on \`$HOST\` at \`$TIMESTAMP\`.\nLatest error:\n\`\`\`$LAST_ERROR\`\`\`"
        fi
        send_slack_notification "$EXIT_MESSAGE"
        echo "[$TIMESTAMP] Watcher script terminated" | tee -a "$LOG_FILE"
        exit 0
    fi
}
trap cleanup SIGINT SIGTERM SIGKILL EXIT

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


START_TIME=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
send_slack_notification ":rocket: *Watcher-$WORKSPACE started* on \`$HOST\` at \`$START_TIME\`"
echo "[$START_TIME] Watcher script started on $HOST" | tee -a "$LOG_FILE"

# Kill any existing tail processes monitoring the log file
ps aux | grep nmdcda | grep "tail -F $LOG_FILE" | awk '{print $2}' | xargs -r kill 2>/dev/null || true

# Start monitoring the log file for errors in background

rm -f "$ERROR_ALERTED_FILE"
tail -F "$LOG_FILE" \
  | grep --line-buffered -E 'ERROR|Exception' \
  | grep --line-buffered -v "$IGNORE_PATTERN" \
  | while read -r line; do
    if [[ ! -f "$ERROR_ALERTED_FILE" || "$line" == "$ALERT_PATTERN" ]]; then
        TIMESTAMP=$(TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y")
        send_slack_notification ":warning: *Watcher-$WORKSPACE ERROR* on \`$HOST\` at \`$TIMESTAMP\`:\n\`\`\`$line\`\`\`"
        touch "$ERROR_ALERTED_FILE"
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