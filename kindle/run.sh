#!/bin/sh
# Private Kodo downloader. Runtime: POSIX sh, curl, FBInk and Kindle lipc.
set -u
cd "$(dirname "$0")" || exit 2
BASE=$(pwd -P)
# Canonical argv allows control.sh to verify this process unambiguously.
[ "$0" = "$BASE/run.sh" ] || exec sh "$BASE/run.sh" "$@"
. "$BASE/common.sh" || exit 2
MODE=loop
case "$#:$*" in 0:) ;; 1:--once) MODE=once ;; *) echo 'usage: run.sh [--once]' >&2; exit 2 ;; esac
load_config || { echo 'configuration_invalid' >&2; exit 2; }
[ -r "$CA_CERT" ] && [ -x "$FBINK" ] || { echo 'dependency_invalid' >&2; exit 2; }
for required in curl lipc-get-prop lipc-set-prop od dd tr cmp wc df awk date ps cat mv rm mkdir rmdir sleep; do
    command -v "$required" >/dev/null 2>&1 || { echo "dependency_missing: $required" >&2; exit 2; }
done
LOCK="$BASE/.running"
mkdir "$LOCK" 2>/dev/null || { echo 'lock_occupied: inspect the existing process before recovery' >&2; exit 3; }
CHILD=''
PREVIOUS=''
OWN_STARTED=''
DISPLAY_KNOWN=0
RECOVERY=none
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
    if ! { printf 'status=%s\nlast_success=%s\nfailures=%s\ndisplay_known=%s\nrecovery=%s\n' \
        "$STATUS" "$LAST_SUCCESS" "$FAILURES" "$DISPLAY_KNOWN" "$RECOVERY" > "$BASE/.state.$$" &&
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

sync_once() {
    RECOVERY=none
    [ "$URL_EXPIRES_AT" -gt "$(date +%s)" ] || { STATUS=url_expired; return 1; }
    free_kib=$(df -Pk "$BASE" 2>/dev/null | awk 'NR == 2 {print $4}')
    is_uint "$free_kib" && [ "$free_kib" -ge 6144 ] || { STATUS=disk_full; return 1; }
    attempt=1
    while :; do
        rm -f "$LOCK/next.png"
        curl_result=0
        # -q disables ~/.curlrc; the signature only appears in the private config.
        run_child curl -q --config "$LOCK/curl.conf" --silent --proto '=https' \
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
    STATUS=updated
    return 0
}

read_state
PREVIOUS=$(lipc-get-prop com.lab126.powerd preventScreenSaver 2>/dev/null) || { echo 'power_read_failed' >&2; exit 2; }
is_uint "$PREVIOUS" || { PREVIOUS=''; echo 'power_value_invalid' >&2; exit 2; }
printf '%s\n' "$PREVIOUS" > "$LOCK/powerd.previous" || exit 2
lipc-set-prop com.lab126.powerd preventScreenSaver 1 >/dev/null 2>&1 || { echo 'power_set_failed' >&2; exit 2; }
printf 'url = "%s"\n' "$CALENDAR_URL" > "$LOCK/curl.conf" || exit 2
: > "$LOCK/ready" || exit 2
notice=$(expiry_notice)
[ -z "$notice" ] || log_event "$notice"
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
    sync_once || result=1
    if [ "$result" -eq 0 ]; then
        LAST_SUCCESS=$(date +%s)
        FAILURES=0
    else
        FAILURES=$((FAILURES + 1))
    fi
    write_state
    rm -f "$LOCK/next.png"
    [ "$MODE" != once ] || exit "$result"
    run_child sleep "$INTERVAL"
done
