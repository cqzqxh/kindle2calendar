#!/bin/sh
# Sourced by run.sh. powerd owns suspend; program its alarm only in the
# readyToSuspend window (seconds from now, not an epoch timestamp).

wake_device() {
    wake_state=$(lipc-get-prop com.lab126.powerd state 2>/dev/null) || return 1
    case "$wake_state" in
        active) return 0 ;;
        screenSaver|readyToSuspend|suspended) ;;
        *) return 1 ;;
    esac
    # PW3 firmware may not expose wakeUp. powerButton is a toggle: guard its state.
    lipc-set-prop com.lab126.powerd powerButton 1 >/dev/null 2>&1 || return 1
    wake_checks=0
    while [ "$wake_checks" -lt 5 ]; do
        wake_state=$(lipc-get-prop com.lab126.powerd state 2>/dev/null) || return 1
        [ "$wake_state" != active ] || return 0
        wake_checks=$((wake_checks + 1))
        run_child sleep 1
    done
    return 1
}

prepare_network() {
    WIFI_PREVIOUS=$(lipc-get-prop com.lab126.wifid enable 2>/dev/null) || return 1
    case "$WIFI_PREVIOUS" in 0|1) ;; *) WIFI_PREVIOUS=''; return 1 ;; esac
    lipc-set-prop com.lab126.wifid enable 1 >/dev/null 2>&1 || return 1
    network_checks=0
    while [ "$network_checks" -lt 15 ]; do
        network_state=$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null) || network_state=''
        case "$network_state" in CONNECTED|CONNECTED:*) return 0 ;; esac
        network_checks=$((network_checks + 1))
        run_child sleep 2
    done
    return 1
}

restore_wifi() {
    [ -n "$WIFI_PREVIOUS" ] || return 0
    lipc-set-prop com.lab126.wifid enable "$WIFI_PREVIOUS" >/dev/null 2>&1 || return 1
    WIFI_PREVIOUS=''
}

wait_for_slot() {
    slot_delay=$(next_sync_delay) || return 1
    NEXT_SYNC=$(($(date +%s) + slot_delay))
    write_state
    # Native UI must run to complete its normal screensaver/suspend transition.
    restore_statusbar || return 1
    # Allow the stock screensaver/suspend path to run while we wait.
    lipc-set-prop com.lab126.powerd preventScreenSaver 0 >/dev/null 2>&1 || return 1
    power_state=$(lipc-get-prop com.lab126.powerd state 2>/dev/null) || return 1
    if [ "$power_state" = active ]; then
        # powerButton toggles: send the sleep request only while active.
        lipc-set-prop com.lab126.powerd powerButton 1 >/dev/null 2>&1 || return 1
    fi
    alarm_armed=0
    observed_power_state=''
    while :; do
        slot_remaining=$((NEXT_SYNC - $(date +%s)))
        [ "$slot_remaining" -gt 0 ] || break
        power_state=$(lipc-get-prop com.lab126.powerd state 2>/dev/null) || return 1
        if [ "$power_state" != "${observed_power_state:-}" ]; then
            log_event "power_state=$power_state next_sync=$NEXT_SYNC"
            observed_power_state=$power_state
        fi
        case "$power_state" in
            readyToSuspend)
                if [ "$alarm_armed" -eq 0 ]; then
                    lipc-set-prop -i com.lab126.powerd rtcWakeup "$slot_remaining" >/dev/null 2>&1 || return 1
                    alarm_armed=1
                    log_event "rtc_armed next_sync=$NEXT_SYNC"
                fi ;;
            active|screenSaver) alarm_armed=0 ;;
            suspended) ;;
            *) return 1 ;;
        esac
        # Short sleeps detect the readyToSuspend window; the CPU stops in
        # suspend. Recheck the epoch after resume, including early/user wakes.
        run_child sleep 5
    done
    NEXT_SYNC=0
    wake_device || return 1
    lipc-set-prop com.lab126.powerd preventScreenSaver 1 >/dev/null 2>&1 || return 1
    run_child sleep 2
    # Stock screensaver/UI may have drawn since our last successful sync.
    pause_statusbar || return 1
    DISPLAY_KNOWN=0
}
