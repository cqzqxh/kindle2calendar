#!/bin/sh
# Shared POSIX helpers. The caller supplies a canonical BASE directory.
LC_ALL=C
export LC_ALL
umask 077

is_uint() {
    case "$1" in ''|*[!0-9]*|0[0-9]*) return 1 ;; esac
    [ "${#1}" -le 10 ]
}

load_config() {
    [ -r "$BASE/config.sh" ] || return 1
    . "$BASE/config.sh" 2>/dev/null || return 1
    INTERVAL=${INTERVAL:-1800}
    POWER_MODE=${POWER_MODE:-rtc}
    RTC_INTERVAL=${RTC_INTERVAL:-0}
    SCREENSAVER_IMAGE=${SCREENSAVER_IMAGE:-}
    is_uint "$RTC_INTERVAL" || return 1
    [ "$RTC_INTERVAL" -eq 0 ] || { [ "$RTC_INTERVAL" -ge 60 ] && [ "$RTC_INTERVAL" -le 86400 ]; } || return 1
    case "$SCREENSAVER_IMAGE" in ''|/*) ;; *) return 1 ;; esac
    TIMEZONE=${TIMEZONE:-Asia/Shanghai}
    case "$POWER_MODE" in rtc|awake) ;; *) return 1 ;; esac
    # Older Kindle firmware may not ship the IANA database. Shanghai has no DST.
    if [ "$TIMEZONE" = Asia/Shanghai ] && [ ! -f /usr/share/zoneinfo/Asia/Shanghai ]; then
        TZ=CST-8
    else
        [ -f "/usr/share/zoneinfo/$TIMEZONE" ] || return 1
        TZ=$TIMEZONE
    fi
    export TZ
    HIDE_STATUS_BAR=${HIDE_STATUS_BAR:-0}
    case "$HIDE_STATUS_BAR" in 0|1) ;; *) return 1 ;; esac
    ALLOW_HTTP_DOWNLOAD=${ALLOW_HTTP_DOWNLOAD:-0}
    case "$ALLOW_HTTP_DOWNLOAD" in 0|1) ;; *) return 1 ;; esac
    DISCOVERY_CONFIG=${DISCOVERY_CONFIG:-/var/local/family-calendar/discovery.json}
    CA_CERT=${CA_CERT:-}
    FBINK=${FBINK:-}
    [ -r "$DISCOVERY_CONFIG" ] || return 1
    is_uint "$INTERVAL" && [ "$INTERVAL" -ge 60 ] || return 1
}

# Seconds until the next local wall-clock slot. Midnight–06:00 uses 2h slots;
# the rest of the day uses 30m slots. Always return a future slot.
next_sync_delay() {
    if [ "${RTC_INTERVAL:-0}" -gt 0 ]; then
        printf '%s\n' "$RTC_INTERVAL"
        return 0
    fi
    slot_clock=$(date '+%H %M %S') || return 1
    set -- $slot_clock
    [ "$#" -eq 3 ] || return 1
    slot_seconds=$(((1$1 - 100) * 3600 + (1$2 - 100) * 60 + 1$3 - 100))
    slot_period=1800
    [ "$slot_seconds" -ge 21600 ] || slot_period=7200
    printf '%s\n' "$((slot_period - slot_seconds % slot_period))"
}

read_field() {
    [ -r "$1" ] || return 0
    awk -v key="$2" 'index($0, key "=") == 1 { print substr($0, length(key) + 2); exit }' "$1" 2>/dev/null
}

read_state() {
    STATUS=$(read_field "$BASE/state" status)
    case "$STATUS" in ''|*[!a-z0-9_]*) STATUS=unknown ;; esac
    LAST_SUCCESS=$(read_field "$BASE/state" last_success)
    is_uint "$LAST_SUCCESS" || LAST_SUCCESS=0
    FAILURES=$(read_field "$BASE/state" failures)
    is_uint "$FAILURES" || FAILURES=0
}

process_start() {
    is_uint "$1" && [ "$1" -gt 1 ] || return 1
    if [ -r "/proc/$1/stat" ]; then
        proc_stat=$(cat "/proc/$1/stat" 2>/dev/null) || return 1
        proc_fields=${proc_stat##*) }
        printf '%s\n' "$proc_fields" | awk '{ if (NF >= 20 && $1 != "Z") print "proc:" $20; else exit 1 }'
    else
        # Development fallback. Kindle installation must verify /proc support.
        proc_state=$(ps -p "$1" -o stat= 2>/dev/null) || return 1
        case "$proc_state" in *Z*) return 1 ;; esac
        proc_time=$(ps -p "$1" -o lstart= 2>/dev/null) || return 1
        [ -n "$proc_time" ] || return 1
        printf 'ps:%s\n' "$proc_time"
    fi
}

process_script_matches() {
    if [ -r "/proc/$1/cmdline" ]; then
        tr '\000' '\n' < "/proc/$1/cmdline" | awk -v path="$BASE/run.sh" '
            NR == 1 { sub(/^.*\//, ""); shell = ($0 == "sh" || $0 == "ash" || $0 == "dash"); next }
            NR == 2 { match_path = ($0 == path) }
            END { exit !(shell && match_path) }'
    else
        proc_command=$(ps -ww -p "$1" -o command= 2>/dev/null) || return 1
        case "$proc_command" in
            "sh $BASE/run.sh"|"sh $BASE/run.sh --once"|"/bin/sh $BASE/run.sh"|"/bin/sh $BASE/run.sh --once") return 0 ;;
            *) return 1 ;;
        esac
    fi
}

lock_identity() {
    [ -d "$BASE/.running" ] || return 1
    LOCK_PID=$(cat "$BASE/.running/pid" 2>/dev/null) || return 1
    LOCK_STARTED=$(cat "$BASE/.running/started" 2>/dev/null) || return 1
    lock_script=$(cat "$BASE/.running/script" 2>/dev/null) || return 1
    [ "$lock_script" = "$BASE/run.sh" ] && [ -n "$LOCK_STARTED" ] || return 1
    lock_actual=$(process_start "$LOCK_PID") || return 1
    [ "$lock_actual" = "$LOCK_STARTED" ] && process_script_matches "$LOCK_PID"
}

report_signal_policy() {
    signal_policy=$(cat "$BASE/.running/signal_policy" 2>/dev/null)
    case "$signal_policy" in
        managed) echo 'signals=TERM:stop,INT:ignore,HUP:ignore' ;;
        foreground) echo 'signals=TERM:stop,INT:stop,HUP:stop (foreground launch)' ;;
        *) echo 'signals=unverified: use control.sh stop' ;;
    esac
}

report_power_recovery() {
    [ -f "$BASE/.running/powerd.restore_failed" ] || return 0
    power_previous=$(cat "$BASE/.running/powerd.previous" 2>/dev/null)
    is_uint "$power_previous" || power_previous=unknown
    printf 'power_restore_failed previous=%s: manual recovery required; lock retained\n' "$power_previous"
}

utc_time() {
    date -u -d "@$1" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null ||
        date -u -r "$1" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || printf '%s\n' "$1"
}
