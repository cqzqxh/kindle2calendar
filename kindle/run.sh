#!/bin/sh
# Kodo private PNG downloader. Requires PW3 shell access, TLS curl, FBInk and lipc.
set -eu
cd "$(dirname "$0")"
BASE=$(pwd)
. "$BASE/config.sh"
case "$CALENDAR_URL" in https://*) ;; *) echo 'CALENDAR_URL 必须使用 HTTPS' >&2; exit 1;; esac
# The URL is placed in a curl config file so its signature is absent from argv.
NL='
'
CR=$(printf '\r')
case "$CALENDAR_URL" in *'"'*|*'\'*|*"$NL"*|*"$CR"*) echo '下载地址格式无效' >&2; exit 1;; esac
case "$INTERVAL" in ''|*[!0-9]*) echo 'INTERVAL 必须是整数' >&2; exit 1;; esac
[ "$INTERVAL" -ge 60 ] || { echo '同步间隔至少 60 秒' >&2; exit 1; }
[ -r "$CA_CERT" ] && [ -x "$FBINK" ] || { echo '缺少证书或 FBInk' >&2; exit 1; }
for command in curl lipc-get-prop lipc-set-prop od dd tr cmp; do
    command -v "$command" >/dev/null || { echo "缺少命令: $command" >&2; exit 1; }
done
# mkdir is atomic; two launchers cannot own the display at the same time.
umask 077
mkdir "$BASE/.running" 2>/dev/null || { echo '日历已运行，或上次断电留下 .running 目录。请先检查进程。' >&2; exit 1; }
echo $$ > "$BASE/.running/pid"
PREVIOUS=''
cleanup() {
    if [ -n "$PREVIOUS" ]; then
        lipc-set-prop com.lab126.powerd preventScreenSaver "$PREVIOUS" || true
    fi
    rm -f "$BASE/.running/pid" "$BASE/.running/curl.conf" "$BASE/.running/next.png"
    rmdir "$BASE/.running" || true
}
trap cleanup EXIT
trap 'exit 0' INT TERM HUP
PREVIOUS=$(lipc-get-prop com.lab126.powerd preventScreenSaver)
lipc-set-prop com.lab126.powerd preventScreenSaver 1
printf 'url = "%s"\n' "$CALENDAR_URL" > "$BASE/.running/curl.conf"
while :; do
    NEXT="$BASE/.running/next.png"
    if curl --config "$BASE/.running/curl.conf" --fail --silent \
        --cacert "$CA_CERT" --connect-timeout 10 --max-time 40 --max-filesize 2097152 \
        --output "$NEXT"; then
        MAGIC=$(dd if="$NEXT" bs=8 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')
        if [ "$MAGIC" = '89504e470d0a1a0a' ]; then
            if ! cmp -s "$NEXT" "$BASE/calendar.png"; then
                if "$FBINK" -c -f -g "file=$NEXT"; then
                    mv "$NEXT" "$BASE/calendar.png"
                else
                    echo 'FBInk 显示失败，尝试恢复上一张图片' >&2
                    [ ! -f "$BASE/calendar.png" ] || "$FBINK" -c -f -g "file=$BASE/calendar.png" || true
                fi
            fi
        else
            echo '响应不是 PNG，保留上次日历' >&2
        fi
    else
        echo '同步失败，保留上次日历' >&2
    fi
    rm -f "$NEXT"
    sleep "$INTERVAL" &
    wait $! || true
done
