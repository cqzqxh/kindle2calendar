#!/bin/sh
# Private Kodo downloader. Runtime: POSIX sh, curl, FBInk and Kindle lipc.
set -u
cd "$(dirname "$0")" || exit 2
BASE=$(pwd -P)
# Canonical argv allows control.sh to verify this process unambiguously.
[ "$0" = "$BASE/run.sh" ] || exec sh "$BASE/run.sh" "$@"
. "$BASE/common.sh" || exit 2
. "$BASE/power.sh" || exit 2
. "$BASE/discover.sh" || exit 2
. "$BASE/statusbar.sh" || exit 2
MODE=loop
case "$#:$*" in 0:) ;; 1:--once) MODE=once ;; *) echo 'usage: run.sh [--once]' >&2; exit 2 ;; esac
load_config || { echo 'configuration_invalid' >&2; exit 2; }
[ -r "$CA_CERT" ] && [ -x "$FBINK" ] || { echo 'dependency_invalid' >&2; exit 2; }
for required in jq openssl stat sort tail grep mktemp cp curl lipc-get-prop lipc-set-prop od dd tr cmp wc df awk date ps cat mv rm mkdir rmdir sleep; do
    command -v "$required" >/dev/null 2>&1 || { echo "dependency_missing: $required" >&2; exit 2; }
done
LOCK="$BASE/.running"
mkdir "$LOCK" 2>/dev/null || { echo 'lock_occupied: inspect the existing process before recovery' >&2; exit 3; }
CHILD=''
PRIVATE_DIR=''
STATUSBAR_PID=''
STATUSBAR_STARTED=''
PREVIOUS=''
OWN_STARTED=''
DISPLAY_KNOWN=0
RECOVERY=none
WIFI_PREVIOUS=''
NEXT_SYNC=0
SIGNAL_POLICY=foreground

cleanup() {
    cleanup_exit=$?
    trap - 0
    trap '' INT TERM HUP
    if [ -n "$CHILD" ]; then
        kill -TERM "$CHILD" 2>/dev/null || :
        wait "$CHILD" 2>/dev/null || :
        CHILD=''
    fi
    # Do not touch a lock replaced by an operator or another process.
    cleanup_pid=$(cat "$LOCK/pid" 2>/dev/null)
    cleanup_started=$(cat "$LOCK/started" 2>/dev/null)
    if [ "$cleanup_pid" = "$$" ] && [ "$cleanup_started" = "$OWN_STARTED" ]; then
        restore_statusbar || { echo 'statusbar_restore_failed' >&2; cleanup_exit=1; }
        restore_wifi || { echo 'wifi_restore_failed' >&2; cleanup_exit=1; }
        power_restored=1
        if [ -n "$PREVIOUS" ]; then
            if ! lipc-set-prop com.lab126.powerd preventScreenSaver "$PREVIOUS" >/dev/null 2>&1; then
                power_restored=0
                cleanup_exit=1
                echo 'power_restore_failed: original value retained for manual recovery' >&2
                # This marker also makes the failure diagnosable if state cannot be written.
                : > "$LOCK/powerd.restore_failed" || echo 'power_failure_marker_write_failed' >&2
                STATUS=power_restore_failed
                FAILURES=$((FAILURES + 1))
                write_state
            fi
        fi
        [ -z "$PRIVATE_DIR" ] || rm -rf "$PRIVATE_DIR" 2>/dev/null
        rm -f "$LOCK/ready" "$LOCK/curl.conf" "$LOCK/next.png" "$LOCK/http.status" "$BASE/.state.$$" 2>/dev/null
        if [ "$power_restored" -eq 1 ]; then
            rm -f "$LOCK/pid" "$LOCK/started" "$LOCK/script" "$LOCK/signal_policy" \
                "$LOCK/powerd.previous" "$LOCK/powerd.restore_failed" 2>/dev/null
            rmdir "$LOCK" 2>/dev/null || echo 'lock_cleanup_failed' >&2
        fi
    fi
    exit "$cleanup_exit"
}
trap cleanup 0
on_signal() {
    if [ "$MODE" = once ]; then exit 1; else exit 0; fi
}
trap on_signal TERM
if [ "${KINDLE_MANAGED:-0}" = 1 ]; then
    # POSIX background shells inherit ignored INT; managed mode deliberately
    # ignores HUP as well. Only TERM/control.sh stop promises orderly shutdown.
    SIGNAL_POLICY=managed
    trap '' INT HUP
else
    trap on_signal INT HUP
fi
OWN_STARTED=$(process_start "$$") || { echo 'process_identity_unavailable' >&2; rmdir "$LOCK"; exit 2; }
if ! { printf '%s\n' "$$" > "$LOCK/pid" && printf '%s\n' "$OWN_STARTED" > "$LOCK/started" &&
       printf '%s\n' "$BASE/run.sh" > "$LOCK/script" && printf '%s\n' "$SIGNAL_POLICY" > "$LOCK/signal_policy"; }; then
    echo 'lock_write_failed' >&2
    exit 2
fi

run_child() {
    "$@" &
    CHILD=$!
    wait "$CHILD"
    child_status=$?
    CHILD=''
    return "$child_status"
}

log_event() {
    log_line="$(date +%s) $1"
    log_size=0
    [ ! -f "$BASE/run.log" ] || log_size=$(wc -c < "$BASE/run.log" 2>/dev/null | tr -d '[:space:]')
    is_uint "$log_size" || log_size=0
    if [ "$((log_size + ${#log_line} + 1))" -gt 131072 ]; then
        mv -f "$BASE/run.log" "$BASE/run.log.1" 2>/dev/null || { echo 'log_write_failed' >&2; return 0; }
    fi
    printf '%s\n' "$log_line" >> "$BASE/run.log" 2>/dev/null || echo 'log_write_failed' >&2
    return 0
}

write_state() {
    if ! { printf 'status=%s\nlast_success=%s\nfailures=%s\ndisplay_known=%s\nrecovery=%s\nnext_sync=%s\n' \
        "$STATUS" "$LAST_SUCCESS" "$FAILURES" "$DISPLAY_KNOWN" "$RECOVERY" "$NEXT_SYNC" > "$BASE/.state.$$" &&
        mv -f "$BASE/.state.$$" "$BASE/state"; } 2>/dev/null; then
        echo 'state_write_failed' >&2
        rm -f "$BASE/.state.$$" 2>/dev/null || :
    fi
    log_event "$STATUS recovery=$RECOVERY failures=$FAILURES"
}

validate_png() {
    PNG_ERROR=invalid_png
    [ -f "$1" ] || return 1
    png_size=$(wc -c < "$1" 2>/dev/null | tr -d '[:space:]')
    is_uint "$png_size" || return 1
    if [ "$png_size" -gt 2097152 ]; then PNG_ERROR=too_large; return 1; fi
    [ "$png_size" -ge 33 ] || return 1
    # Header only: FBInk must decode the image before it can replace the cache.
    png_header=$(dd if="$1" bs=26 count=1 2>/dev/null | od -An -tx1 | tr -d '[:space:]')
    [ "$png_header" = '89504e470d0a1a0a0000000d4948445200000430000005a80800' ]
}

restore_previous() {
    DISPLAY_KNOWN=0
    RECOVERY=no_previous
    if validate_png "$BASE/calendar.png"; then
        RECOVERY=restore_failed
        if run_child "$FBINK" -c -f -g "file=$BASE/calendar.png" >/dev/null 2>&1; then
            DISPLAY_KNOWN=1
            RECOVERY=restored
        fi
    fi
}

update_screensaver() {
    [ -n "$SCREENSAVER_IMAGE" ] || return 0
    # Atomic replacement keeps linkss from seeing a partially copied PNG.
    if ! cp "$BASE/calendar.png" "$SCREENSAVER_IMAGE.tmp" 2>/dev/null; then
        rm -f "$SCREENSAVER_IMAGE.tmp" 2>/dev/null
        return 1
    fi
    if ! mv -f "$SCREENSAVER_IMAGE.tmp" "$SCREENSAVER_IMAGE" 2>/dev/null; then
        rm -f "$SCREENSAVER_IMAGE.tmp" 2>/dev/null
        return 1
    fi
}

sync_once() {
    RECOVERY=none
    if ! discover_calendar "$DISCOVERY_CONFIG" "$CA_CERT" "$PRIVATE_DIR/curl.conf" >/dev/null 2>&1; then
        STATUS=discovery_failed
        return 1
    fi
    free_kib=$(df -Pk "$BASE" 2>/dev/null | awk 'NR == 2 {print $4}')
    is_uint "$free_kib" && [ "$free_kib" -ge 6144 ] || { STATUS=disk_full; return 1; }
    download_proto='=https'
    [ "$ALLOW_HTTP_DOWNLOAD" != 1 ] || download_proto='=http,https'
    attempt=1
    while :; do
        rm -f "$LOCK/next.png"
        curl_result=0
        # -q disables ~/.curlrc; the signature only appears in the private config.
        run_child curl -q --config "$PRIVATE_DIR/curl.conf" --silent --proto "$download_proto" \
            --cacert "$CA_CERT" --connect-timeout 10 --max-time 40 --max-filesize 2097152 \
            --write-out '%{http_code}' --output "$LOCK/next.png" > "$LOCK/http.status" 2>/dev/null || curl_result=$?
        http_status=$(cat "$LOCK/http.status" 2>/dev/null)
        retry=0
        if [ "$curl_result" -ne 0 ]; then
            STATUS=download_failed
            case "$curl_result" in 5|6|7|18|28|52|55|56) STATUS=network_failed; retry=1 ;; 63) STATUS=too_large ;; esac
        elif [ "$http_status" = 200 ]; then
            break
        else
            case "$http_status" in
                [1-5][0-9][0-9]) STATUS="http_$http_status" ;;
                *) STATUS=http_invalid ;;
            esac
            case "$http_status" in 5[0-9][0-9]) retry=1 ;; esac
        fi
        rm -f "$LOCK/next.png"
        [ "$retry" -eq 1 ] && [ "$attempt" -lt 2 ] || return 1
        attempt=$((attempt + 1))
        run_child sleep 5
    done
    validate_png "$LOCK/next.png" || { STATUS=$PNG_ERROR; return 1; }
    if [ "$DISPLAY_KNOWN" -eq 1 ] && cmp -s "$LOCK/next.png" "$BASE/calendar.png"; then
        update_screensaver || { STATUS=screensaver_save_failed; return 1; }
        STATUS=unchanged
        return 0
    fi
    if ! run_child "$FBINK" -c -f -g "file=$LOCK/next.png" >/dev/null 2>&1; then
        STATUS=draw_failed
        restore_previous
        return 1
    fi
    if ! mv -f "$LOCK/next.png" "$BASE/calendar.png" 2>/dev/null; then
        STATUS=save_failed
        restore_previous
        return 1
    fi
    DISPLAY_KNOWN=1
    update_screensaver || { STATUS=screensaver_save_failed; return 1; }
    STATUS=updated
    return 0
}

read_state
PREVIOUS=$(lipc-get-prop com.lab126.powerd preventScreenSaver 2>/dev/null) || { echo 'power_read_failed' >&2; exit 2; }
is_uint "$PREVIOUS" || { PREVIOUS=''; echo 'power_value_invalid' >&2; exit 2; }
printf '%s\n' "$PREVIOUS" > "$LOCK/powerd.previous" || exit 2
lipc-set-prop com.lab126.powerd preventScreenSaver 1 >/dev/null 2>&1 || { echo 'power_set_failed' >&2; exit 2; }
PRIVATE_DIR=$(mktemp -d /tmp/family-calendar-run.XXXXXX) || exit 2
if [ "$MODE" = loop ] && [ "$POWER_MODE" = rtc ]; then
    wake_device || { echo 'power_wake_failed' >&2; exit 2; }
    run_child sleep 2
fi
pause_statusbar || { echo 'statusbar_pause_failed' >&2; exit 2; }
: > "$LOCK/ready" || exit 2
if [ "$MODE" = loop ] && validate_png "$BASE/calendar.png"; then
    if run_child "$FBINK" -c -f -g "file=$BASE/calendar.png" >/dev/null 2>&1; then
        DISPLAY_KNOWN=1
        log_event cache_displayed
    else
        log_event cache_draw_failed
    fi
fi
while :; do
    result=0
    if [ "$MODE" = loop ] && [ "$POWER_MODE" = rtc ]; then
        if ! prepare_network; then
            STATUS=network_wake_failed
            result=1
        fi
    fi
    if [ "$result" -eq 0 ]; then sync_once || result=1; fi
    if ! restore_wifi; then
        STATUS=wifi_restore_failed
        result=1
    fi
    if [ "$result" -eq 0 ]; then
        LAST_SUCCESS=$(date +%s)
        FAILURES=0
    else
        FAILURES=$((FAILURES + 1))
    fi
    write_state
    rm -f "$LOCK/next.png"
    [ "$MODE" != once ] || exit "$result"
    if [ "$POWER_MODE" = rtc ]; then
        if ! wait_for_slot; then
            STATUS=wake_schedule_failed
            FAILURES=$((FAILURES + 1))
            NEXT_SYNC=0
            write_state
            exit 1
        fi
    else
        run_child sleep "$INTERVAL"
    fi
done
