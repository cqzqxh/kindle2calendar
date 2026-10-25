#!/bin/sh
# No boot integration and no automatic stale-lock removal.
set -u
cd "$(dirname "$0")" || exit 2
BASE=$(pwd -P)
. "$BASE/common.sh" || exit 2
case "${1:-}" in
    start)
        [ "$#" -eq 1 ] || exit 2
        [ ! -e "$BASE/.running" ] || { echo 'lock_occupied: inspect status before recovery' >&2; exit 3; }
        load_config || { echo 'configuration_invalid' >&2; exit 2; }
        # POSIX background execution ignores INT on shell entry. Make the HUP
        # policy explicit too; TERM is the supported managed shutdown signal.
        (
            trap '' INT HUP
            KINDLE_MANAGED=1
            export KINDLE_MANAGED
            exec sh "$BASE/run.sh"
        ) </dev/null >/dev/null 2>&1 &
        launch_pid=$!
        checks=0
        while [ "$checks" -lt 10 ]; do
            if lock_identity && [ "$LOCK_PID" = "$launch_pid" ] && [ -f "$BASE/.running/ready" ]; then
                echo 'running'
                report_signal_policy
                exit 0
            fi
            kill -0 "$launch_pid" 2>/dev/null || { wait "$launch_pid"; echo 'start_failed' >&2; exit 2; }
            checks=$((checks + 1))
            sleep 1
        done
        if lock_identity && [ "$LOCK_PID" = "$launch_pid" ]; then kill -TERM "$LOCK_PID"; fi
        echo 'start_unconfirmed: inspect status' >&2
        exit 1 ;;
    status)
        [ "$#" -eq 1 ] || exit 2
        status_code=1
        if lock_identity && [ -f "$BASE/.running/ready" ]; then
            echo "running pid=$LOCK_PID"
            report_signal_policy
            status_code=0
        elif [ -d "$BASE/.running" ]; then
            echo 'unverified_lock: manual inspection required'
        else
            echo 'stopped'
        fi
        report_power_recovery
        read_state
        printf 'status=%s\nfailures=%s\n' "$STATUS" "$FAILURES"
        next_sync=$(read_field "$BASE/state" next_sync)
        if [ "$status_code" -eq 0 ] && is_uint "$next_sync" && [ "$next_sync" -gt 0 ]; then
            printf 'next_sync=%s\n' "$(utc_time "$next_sync")"
        fi
        if [ "$LAST_SUCCESS" -eq 0 ]; then echo '尚无成功同步'; else printf 'last_success=%s\n' "$(utc_time "$LAST_SUCCESS")"; fi
        if load_config; then
            echo 'discovery=timestamped_list'
        else
            echo 'configuration_invalid'
            status_code=2
        fi
        exit "$status_code" ;;
    stop)
        [ "$#" -eq 1 ] || exit 2
        [ -d "$BASE/.running" ] || { echo 'stopped'; exit 0; }
        lock_identity || { report_power_recovery >&2; echo 'identity_unverified: refusing to signal or remove lock' >&2; exit 3; }
        stop_pid=$LOCK_PID
        stop_started=$LOCK_STARTED
        kill -TERM "$stop_pid" 2>/dev/null || { echo 'stop_signal_failed' >&2; exit 1; }
        checks=0
        while [ "$checks" -lt 15 ]; do
            current_started=$(process_start "$stop_pid") || current_started=''
            if [ "$current_started" != "$stop_started" ]; then
                if [ ! -d "$BASE/.running" ]; then echo 'stopped'; exit 0; fi
                report_power_recovery >&2
                echo 'stopped_with_residual_lock: manual inspection required' >&2
                exit 1
            fi
            checks=$((checks + 1))
            sleep 1
        done
        echo 'stop_timeout: no KILL sent' >&2
        exit 1 ;;
    *) echo 'usage: control.sh start|status|stop' >&2; exit 2 ;;
esac
