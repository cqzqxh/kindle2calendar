#!/bin/sh
# Suspend only the existing status-bar driver while this calendar owns the display.
# The caller initializes identity fields before installing its cleanup trap.
pause_statusbar() {
    [ "$HIDE_STATUS_BAR" = 1 ] || return 0
    command -v pidof >/dev/null 2>&1 || return 1
    statusbar_pid=$(pidof JunoStatusBarDriver 2>/dev/null) || return 0
    is_uint "$statusbar_pid" || return 1
    statusbar_state=$(ps -p "$statusbar_pid" -o stat= 2>/dev/null) || return 1
    case "$statusbar_state" in *T*) return 0 ;; esac
    statusbar_started=$(process_start "$statusbar_pid") || return 1
    STATUSBAR_PID=$statusbar_pid
    STATUSBAR_STARTED=$statusbar_started
    kill -STOP "$statusbar_pid" 2>/dev/null || return 1
}

restore_statusbar() {
    [ -n "$STATUSBAR_PID" ] || return 0
    statusbar_current=$(process_start "$STATUSBAR_PID") || return 0
    # Never signal a PID reused by a different process.
    [ "$statusbar_current" = "$STATUSBAR_STARTED" ] || return 0
    kill -CONT "$STATUSBAR_PID" 2>/dev/null || return 1
    STATUSBAR_PID=''
    STATUSBAR_STARTED=''
}
