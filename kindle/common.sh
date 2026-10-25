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
    CALENDAR_URL=${CALENDAR_URL:-}
    CA_CERT=${CA_CERT:-}
    FBINK=${FBINK:-}
    case "$CALENDAR_URL" in https://*) ;; *) return 1 ;; esac
    case "$CALENDAR_URL" in *'"'*|*"'"*|*'\'*|*'#'*|*[[:space:][:cntrl:]]*) return 1 ;; esac
    url_rest=${CALENDAR_URL#https://}
    url_host=${url_rest%%/*}
    case "$url_host" in ''|*'@'*|*'?'*|*':'*) return 1 ;; esac
    case "$url_rest" in */*\?*) ;; *) return 1 ;; esac
    url_query=${CALENDAR_URL#*\?}
    url_expiry=''
    while :; do
        url_part=${url_query%%&*}
        case "$url_part" in
            e=*) [ -z "$url_expiry" ] || return 1
                 url_expiry=${url_part#e=}
                 is_uint "$url_expiry" || return 1 ;;
        esac
        case "$url_query" in *'&'*) url_query=${url_query#*&} ;; *) break ;; esac
    done
    is_uint "$url_expiry" || return 1
    URL_EXPIRES_AT=${URL_EXPIRES_AT:-$url_expiry}
    is_uint "$URL_EXPIRES_AT" && [ "$URL_EXPIRES_AT" = "$url_expiry" ] || return 1
    is_uint "$INTERVAL" && [ "$INTERVAL" -ge 60 ] || return 1
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

expiry_notice() {
    expiry_now=$(date +%s)
    if [ "$URL_EXPIRES_AT" -le "$expiry_now" ]; then
        printf '%s\n' url_expired
    elif [ "$((URL_EXPIRES_AT - expiry_now))" -lt 604800 ]; then
        printf '%s\n' url_expires_within_7_days
    fi
}
