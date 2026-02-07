#!/bin/bash
set -euo pipefail

# Default values
WORKSPACE="prod"
CONF=/global/homes/n/nmdcda/nmdc_automation/$WORKSPACE/site_configuration_nersc_$WORKSPACE.toml
HOST=$(hostname)
LOG_FILE=watcher-$WORKSPACE.log
PID_FILE=watcher-$WORKSPACE.pid
HOST_FILE=host-$WORKSPACE.last
RESTART_FLAG="/tmp/watcher_${WORKSPACE}_restarting"
KILL_FLAG="/tmp/watcher_${WORKSPACE}_kill"
PVENV=/global/cfs/cdirs/m3408/nmdc_automation/$WORKSPACE/nmdc_automation/.venv
COMMAND=""   # default start/restart watcher when script called

# Global state flags
CLEANED_UP=0
RESTARTING=0
MISMATCH=0
HELP=0
MUTE=0
TEST=0
ACTUAL=0
KILL_PID=""
WATCHER_PID=""
OLD_PID=""
OLD_HOST=""
TAIL_PID=""
LAST_ALERT=""
LAST_ERROR=""
IGNORE_PATTERN="Error removing directory /tmp: \[Errno 13\] Permission denied: .*/tmp|['\"]error['\"]:[[:space:]]*['\"][[:space:]]*['\"]"
ALERT_PATTERN='Internal Server Error'
TRACEBACK_LINES=()
ERROR_SUMMARY=""
WATCH_CMD=()

# Help message
show_help() {
  echo "Usage: $0 [COMMAND] [--conf PATH] [OPTIONS]"
  echo
  echo "Commands:"
  echo "  stop                   Stop the running watcher"
  echo "  status                 Show watcher status"
  echo
  echo "Options:"
  echo "  -c, --conf PATH        Path to site config TOML   (default: $CONF)"
  echo "  -m, --mute             Silence Slack notifs" 
  echo "  -t, --test             Run wrapper in test mode" 
  echo "  -a, --actual           Run wrapper in test mode with watcher code" 
  echo "  -h, --help             Show this help message"
  HELP=1
}

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        stop|status)    COMMAND="$1"; shift;;
        -c|--conf)      CONF="$2"; shift 2 ;;
        -m|--mute)      MUTE=1; shift ;;
        -t|--test)      TEST=1; shift ;;
        -a|--actual)    TEST=1; ACTUAL=1; shift ;;
        -h|--help)      show_help; exit 0 ;;
        *)              echo "Unknown option: $1"; show_help; exit 1 ;;
    esac
done

# process developer options

if [[ ${TEST:-0} -eq 1 ]]; then
    if [[ "${VIRTUAL_ENV:0}" != "$PVENV" ]]; then
        echo "Warning: Different poetry environment ${VIRTUAL_ENV:0}"
        PVENV="${VIRTUAL_ENV:0}"
    fi
    CONF=./site_configuration.toml
    WATCH_CMD=(python -u watcher.py)
fi
if [[ ${TEST:-0} -eq 0 || ${ACTUAL:-0} -eq 1 ]]; then
    WATCH_CMD=(env PYTHONPATH="$(pwd)/nmdc_automation" \
            python -u -m nmdc_automation.run_process.run_workflows watcher \
            --config "$CONF" daemon)
fi

SLACK_WEBHOOK_URL=$(grep 'slack_webhook' "$CONF" | sed 's/.*= *"\(.*\)"/\1/')

# ----------- Functions ----------- 
jaws() {
        JAWS_USER_CONFIG=~/jaws.conf \
        JAWS_CLIENT_CONFIG=/global/cfs/cdirs/m3408/jaws-install/jaws-client/nmdc-prod/jaws-prod.conf \
        shifter --image=doejgi/jaws-client:latest jaws "$@"
    }

send_slack_notification() {
    if [[ "$MUTE" -eq 1 ]]; then
        return
    fi
    local message="$1"
    curl -s -X POST -H 'Content-type: application/json' \
         --data "{\"text\": \"$message\"}" \
         "$SLACK_WEBHOOK_URL" > /dev/null
}

get_timestamp() {
    TZ="America/Los_Angeles" date "+%a %b %d %T %Z %Y" 2>/dev/null || true
}

log() {
    if [ -n "$1" ]; then
        # Direct message
        printf '[%s] %s\n' "$(get_timestamp)" "$1" | tee -a "$LOG_FILE" 
    else
        # Read from stdin (for piped input)
        while IFS= read -r line; do
            printf '[%s] %s\n' "$(get_timestamp)" "$line" | tee -a "$LOG_FILE" 
        done
    fi
}

log_status() {
    log "CLEANUP RESTARTING MISMATCH KILL_PID HELP"
    log "$CLEANED_UP $RESTARTING $MISMATCH $KILL_PID $HELP"
}

check_host_match() {
    if [[ -f "$HOST_FILE" ]]; then
        read -r OLD_HOST < "$HOST_FILE"
        if [[ -n "$OLD_HOST" && "$OLD_HOST" != "$HOST" ]]; then
            log "Host mismatch: existing watcher was on '$OLD_HOST', current host is '$HOST'."
            return 1
        fi
    fi
    return 0
}

kill_tails() {
    # Ensure no leftover tail processes are running for full log file
    pkill -u "$USER" -f "tail -n 0 -F $LOG_FILE" 2>/dev/null || true
}

cleanup() {
    # cleanup() may be invoked multiple times (signals, errors, exits). Ensures side effects only run once.
    if [[ ${CLEANED_UP:-0} -eq 1 ]]; then
        return
    fi
    CLEANED_UP=1
 
    # If this process is being replaced, exit quietly
    if [[ -f "$RESTART_FLAG" ]]; then
        log "Watcher exiting due to restart"
        rm -f "$RESTART_FLAG"
        exit 0
    fi
    
    # Manual stop is a hard termination with notification.
    if [[ -f "$KILL_FLAG" ]]; then
        rm -f "$KILL_FLAG"
        exit 0
    fi

    # Always clean up tail process if it exists    
    if [[ -n "${TAIL_PID:-}" ]]; then
        kill "$TAIL_PID" 2>/dev/null || true 
        pkill -P "$TAIL_PID" 2>/dev/null || true
    fi
    kill_tails

    # HELP or MISMATCH intentionally terminate without Slack noise.
    if [[ ${HELP:-0} -eq 1 || ${MISMATCH:-0} -eq 1 ]]; then
        exit 0
    fi

    # NORMAL TERMINATION: Send termination notification, include last error if present.
    kill "$WATCHER_PID" 2>/dev/null || true
    EXIT_MESSAGE=":x: *Watcher-$WORKSPACE script terminated* on \`$HOST\` at \`$(get_timestamp)\`"
    if [[ -n "${LAST_ERROR:-}" && "${LAST_ERROR:-}" != "${LAST_ALERT:-}" ]]; then
        EXIT_MESSAGE+="\nLatest error:\n\`\`\`${LAST_ERROR}\`\`\`"
    fi
    send_slack_notification "$EXIT_MESSAGE"
    log "Watcher script terminated"
    log_status
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# process commands
if [[ "$COMMAND" == "stop" || "$COMMAND" == "status" ]]; then
    if ! check_host_match; then
        echo "Can't $COMMAND watcher from a different host."
        MISMATCH=1
        exit 1
    fi

    if [[ -f "$PID_FILE" ]]; then
        read -r OLD_PID < "$PID_FILE"
        if ps -p "$OLD_PID" > /dev/null 2>&1; then
            if [[ "$COMMAND" == "stop" ]]; then
                echo "Stopping watcher PID $OLD_PID..."
                KILL_PID="$OLD_PID"; touch "$KILL_FLAG"
                send_slack_notification ":octagonal_sign: *Watcher-$WORKSPACE manually stopped* on \`$HOST\` at \`$(get_timestamp)\`"
                log "Watcher script manually terminated"
                kill "$KILL_PID" 2>/dev/null 
                kill_tails
            else
                echo "Watcher is running (PID $OLD_PID)"
                ps -u "$USER" -o pid,user,etime,command | awk 'NR==1 || (/watcher/ && !/awk/)'
                echo -e "\nChecking JAWS jobs going back 1 day..."
                jaws history | awk '/status/ { count[$0]++ } END { for (k in count) print count[k], k }' | sort -n 
            fi
        else
            echo "Watcher PID $OLD_PID not running"
        fi
    else
        [[ "$COMMAND" == "stop" ]] \
            && echo "No PID file found; watcher may not be running" \
            || echo "Watcher not running" 
    fi
    HELP=1
    exit 0
fi



# Kill existing process only if it's the correct watcher on this host
if ! check_host_match; then
    log "Aborting startup due to host mismatch."
    MISMATCH=1
    exit 1
fi

if [[ "${VIRTUAL_ENV:0}" != "$PVENV" ]]; then
    log "Incorrect poetry environment. Aborting."
    MISMATCH=1
    exit 1
fi

# Look for an existing watcher process
if [[ -f "$PID_FILE" ]] && read -r OLD_PID < "$PID_FILE" && ps -p "$OLD_PID" > /dev/null 2>&1; then
    # check for PID process
    COMMAND_NAME=$(ps -p "$OLD_PID" -o comm=)
    PROC_COMMAND=$(ps -p "$OLD_PID" -o args=)
    # check command name and command process include python and watcher
    if [[ "$COMMAND_NAME" == *python* && "$PROC_COMMAND" == *watcher* ]]; then
        log "Found running watcher process $OLD_PID: $COMMAND_NAME"
        RESTARTING=1
        touch "$RESTART_FLAG"
        send_slack_notification ":arrows_counterclockwise: *Watcher-$WORKSPACE script refresh* on \`$HOST\` at \`$(get_timestamp)\` (replacing PID \`$OLD_PID\`)"
        KILL_PID="$OLD_PID"
        kill "$KILL_PID" 2>/dev/null || true
    else
        log "Process with PID $OLD_PID is not the watcher, skipping kill"
        MISMATCH=1
        exit 1
    fi
else
    log "No active process found for PID $OLD_PID"
fi
kill_tails

# Start monitoring the log file for errors in background
tail -n 0 -F "$LOG_FILE" | while IFS= read -r line; do
    # skip known patterns
    [[ -n "$IGNORE_PATTERN" && "$line" =~ $IGNORE_PATTERN ]] && continue
    
    # begin python traceback
    if [[ "$line" == *"Traceback (most recent call last):"* ]]; then
        TRACEBACK_LINES=("$line")
        TRACEBACK_ACTIVE=1
        continue
    fi
    if [[ ${TRACEBACK_ACTIVE:-0} -eq 1 ]]; then
        TRACEBACK_LINES+=("$line")

        # Only send on the **final exception line**
        if [[ "$line" =~ [A-Za-z]+Error:|Exception: ]]; then
            ERROR_SUMMARY=$(printf "%s\n" "${TRACEBACK_LINES[@]}" \
                | grep -E "[A-Za-z]+Error:|Exception:" \
                | tail -n1 \
                | sed -E 's/with url: .*//' \
                | sed -E 's/^[^:]+: //' )
            ERROR_SUMMARY=${ERROR_SUMMARY:-"Unknown error"}
            LAST_ERROR="$ERROR_SUMMARY"

            if [[ -n "$ERROR_SUMMARY" && "$ERROR_SUMMARY" != "$LAST_ALERT" ]]; then
                send_slack_notification ":warning: *Watcher-$WORKSPACE ERROR* on \`$HOST\` at \`$(get_timestamp)\`:\n\`\`\`$ERROR_SUMMARY\`\`\`"
                LAST_ALERT="$ERROR_SUMMARY"
            fi
            # Reset traceback detection
            TRACEBACK_LINES=()
            TRACEBACK_ACTIVE=0
        fi
        continue
    fi

    # single line error detection
    shopt -s nocasematch
    if [[ "$line" =~ error|exception ]]; then
        # [[ "$line" =~ $IGNORE_PATTERN ]] && continue # taken care of above
        LAST_ERROR="$line"
        if [[ "$line" != "$LAST_ALERT" || "$line" == *"$ALERT_PATTERN"* ]]; then
            send_slack_notification ":warning: *Watcher-$WORKSPACE ERROR* on \`$HOST\` at \`$(get_timestamp)\`:\n\`\`\`$line\`\`\`"
            LAST_ALERT="$line"
        fi
    fi
    shopt -u nocasematch
done &
TAIL_PID=$!

if [[ ${RESTARTING:-0} -eq 0 ]]; then 
    send_slack_notification ":rocket: *Watcher-$WORKSPACE started* on \`$HOST\` at \`$(get_timestamp)\`"
fi
log "Watcher script started on $HOST"
log_status
RESTARTING=0
CLEANED_UP=0

"${WATCH_CMD[@]}" \
    > >(tee -a "$LOG_FILE") 2>&1 &

WATCHER_PID=$!
echo "$WATCHER_PID" > "$PID_FILE"
echo "$HOST" > "$HOST_FILE"
wait "$WATCHER_PID"
cleanup