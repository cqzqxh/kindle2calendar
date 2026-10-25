#!/bin/sh
# PW3 live-clock experiment over a fixed PNG; independent of cloud downloads.
set -eu
cd "$(dirname "$0")"
BASE=$(pwd)
STATE="$BASE/.clock-demo"
FBINK=${FBINK:-/mnt/us/usbnet/bin/fbink}
IMAGE=${IMAGE:-$BASE/preview_202610241720.png}
FONT=${FONT:-/usr/java/lib/fonts/Amazon-Ember-Regular.ttf}
# This experiment uses Shanghai time explicitly, independent of device settings.
export TZ=CST-8
case "${1:-start}" in
    stop)
        if [ -f "$STATE/pid" ]; then
            PID=$(cat "$STATE/pid")
            case "$PID" in ''|*[!0-9]*) exit 1;; esac
            kill -TERM "$PID"
        fi
        exit 0 ;;
    start) ;;
    *) echo 'Usage: clock-demo.sh [start|stop]' >&2; exit 1 ;;
esac
[ -x "$FBINK" ] && [ -r "$IMAGE" ] && [ -r "$FONT" ]
mkdir "$STATE" || { echo 'Clock already running; inspect .clock-demo/pid' >&2; exit 1; }
echo $$ > "$STATE/pid"
PREVIOUS=''
SLEEP_PID=''
UI_PID=''
cleanup() {
    [ -z "$SLEEP_PID" ] || kill "$SLEEP_PID" 2>/dev/null || true
    "$FBINK" -q -c -f -w -g "file=$IMAGE" || true
    [ -z "$UI_PID" ] || kill -CONT "$UI_PID" 2>/dev/null || true
    [ -z "$PREVIOUS" ] || lipc-set-prop com.lab126.powerd preventScreenSaver "$PREVIOUS" || true
    rm -f "$STATE/pid"
    rmdir "$STATE" || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM HUP
PREVIOUS=$(lipc-get-prop com.lab126.powerd preventScreenSaver)
lipc-set-prop com.lab126.powerd preventScreenSaver 1
# The native status bar otherwise repaints its own clock over the calendar.
UI_PID=$(pidof Xorg || true)
[ -z "$UI_PID" ] || kill -STOP "$UI_PID"
"$FBINK" -q -c -f -w -g "file=$IMAGE"
while :; do
    CLOCK=$(date '+%H:%M')
    # Compose in memory, then submit one non-flashing refresh of this region.
    "$FBINK" -q -b -m -t "regular=$FONT,px=52,top=20,bottom=1362,left=790,right=47,padding=BOTH,notrunc" "$CLOCK"
    "$FBINK" -q -w -s top=20,left=790,width=235,height=66
    printf '%s clock=%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$CLOCK"
    # Recompute each time so execution time does not accumulate into drift.
    SECOND=$(date '+%S')
    SECOND=${SECOND#0}
    sleep "$((60 - SECOND))" &
    SLEEP_PID=$!
    wait "$SLEEP_PID" || true
    SLEEP_PID=''
done
