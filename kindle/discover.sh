#!/bin/sh
# Sourced by run.sh. Existing curl + OpenSSL + jq only; no Python on Kindle.
# Every network child goes through run_child so control.sh stop can reap it.

discovery_clock() {
    if [ -r /proc/uptime ]; then
        awk '{printf "%d\n", $1}' /proc/uptime
    else
        date +%s
    fi
}

discovery_date() {
    date -d "@$1" "$2" 2>/dev/null || date -r "$1" "$2" 2>/dev/null
}

discovery_hmac() {
    # Implement HMAC with private pad files. Passing -hmac SK would expose SK in ps.
    # OpenSSL 1.0.2 and BusyBox awk/printf are sufficient, including NUL pad bytes.
    if [ ! -f "$D_TMP/inner" ]; then
        D_size=$(wc -c < "$D_TMP/key" | tr -d '[:space:]') || return 1
        if [ "$D_size" -gt 64 ]; then
            openssl dgst -sha1 -binary "$D_TMP/key" > "$D_TMP/key.hash" 2>/dev/null || return 1
            mv -f "$D_TMP/key.hash" "$D_TMP/key" || return 1
        fi
        for D_pad_name in inner outer; do
            case "$D_pad_name" in inner) D_xor=54 ;; outer) D_xor=92 ;; esac
            D_pad=$(od -An -tu1 "$D_TMP/key" | awk -v pad="$D_xor" '
                function bxor(a,b, r,p) {
                    r=0; p=1
                    while (a || b) { if (a%2 != b%2) r+=p; a=int(a/2); b=int(b/2); p*=2 }
                    return r
                }
                { for (i=1; i<=NF; i++) bytes[n++]=$i }
                END { for (i=0; i<64; i++) printf "\\0%03o", bxor(bytes[i]+0,pad) }') || return 1
            printf '%b' "$D_pad" > "$D_TMP/$D_pad_name" || return 1
        done
    fi
    { cat "$D_TMP/inner"; cat "$1"; } > "$D_TMP/message" || return 1
    openssl dgst -sha1 -binary "$D_TMP/message" > "$D_TMP/digest" 2>/dev/null || return 1
    { cat "$D_TMP/outer"; cat "$D_TMP/digest"; } > "$D_TMP/message" || return 1
    openssl dgst -sha1 -binary "$D_TMP/message" > "$D_TMP/digest" 2>/dev/null || return 1
    openssl base64 -A -in "$D_TMP/digest" 2>/dev/null | tr '+/' '-_'
}

discovery_impl() {
    [ "$(stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1" 2>/dev/null)" = 600 ] || return 1
    D_scheme=https
    [ "${ALLOW_HTTP_DOWNLOAD:-0}" != 1 ] || D_scheme='https?'
    jq -e --arg scheme "$D_scheme" '
        type == "object" and
        (.access_key | type == "string" and test("^[A-Za-z0-9_-]{1,128}$")) and
        (.secret_key | type == "string" and test("^[A-Za-z0-9_-]{1,128}$")) and
        (.bucket | type == "string" and test("^[A-Za-z0-9_-]{1,128}$")) and
        (.screen_id | type == "string" and test("^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")) and
        (.domain | type == "string" and test("^" + $scheme + "://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?/?$"))
    ' "$1" >/dev/null 2>&1 || return 1
    D_AK=$(jq -r .access_key "$1") || return 1
    # jq -j avoids an extra newline in the HMAC key.
    jq -j .secret_key "$1" > "$D_TMP/key" || return 1
    D_BUCKET=$(jq -r .bucket "$1") || return 1
    D_SCREEN=$(jq -r .screen_id "$1") || return 1
    D_DOMAIN=$(jq -r '.domain | rtrimstr("/")' "$1") || return 1
    D_now=$(date +%s) || return 1
    D_stamp=$(discovery_date "$D_now" '+%Y%m%d%H%M%S') || return 1
    # Anchor at local noon, then step back 24h; DST transitions cannot repeat a day.
    D_parts=$(discovery_date "$D_now" '+%H %M %S') || return 1
    set -- $D_parts
    D_noon=$((D_now + (12 - (1$1 - 100)) * 3600 - (1$2 - 100) * 60 - (1$3 - 100)))
    D_end=$(discovery_clock) || return 1
    D_end=$((D_end + 90))
    D_day=0
    D_newest=''
    while [ "$D_day" -lt 7 ]; do
        D_date=$(discovery_date "$((D_noon - D_day * 86400))" '+%Y%m%d') || return 1
        D_prefix="family-calendar/$D_SCREEN/$D_date/"
        D_encoded=$(printf '%s' "$D_prefix" | jq -sRr @uri) || return 1
        D_marker=''
        : > "$D_TMP/markers"
        D_page=0
        while :; do
            D_page=$((D_page + 1))
            [ "$D_page" -le 100 ] || return 1
            D_remaining=$((D_end - $(discovery_clock)))
            [ "$D_remaining" -gt 0 ] || return 1
            [ "$D_remaining" -le 15 ] || D_remaining=15
            D_path="/list?bucket=$D_BUCKET&prefix=$D_encoded&limit=1000&marker=$D_marker"
            D_utc=$(date -u '+%Y%m%dT%H%M%SZ') || return 1
            printf 'GET %s\nHost: rsf.qiniuapi.com\nContent-Type: application/x-www-form-urlencoded\nX-Qiniu-Date: %s\n\n' \
                "$D_path" "$D_utc" > "$D_TMP/signing" || return 1
            D_sig=$(discovery_hmac "$D_TMP/signing") || return 1
            {
                printf 'url = "https://rsf.qiniuapi.com%s"\n' "$D_path"
                printf 'header = "Authorization: Qiniu %s:%s"\n' "$D_AK" "$D_sig"
                printf 'header = "Content-Type: application/x-www-form-urlencoded"\n'
                printf 'header = "X-Qiniu-Date: %s"\n' "$D_utc"
            } > "$D_TMP/request.conf" || return 1
            run_child curl -q --config "$D_TMP/request.conf" --silent --proto '=https' \
                --noproxy '*' --cacert "$D_CA" --connect-timeout 5 --max-time "$D_remaining" \
                --max-filesize 2097152 --write-out '%{http_code}' --output "$D_TMP/page.json" > "$D_TMP/status" 2>/dev/null || return 1
            D_http=$(cat "$D_TMP/status")
            [ "$D_http" = 200 ] || return 1
            [ "$(wc -c < "$D_TMP/page.json")" -le 2097152 ] || return 1
            jq -e 'type == "object" and (has("error") | not) and
                (.items | type == "array" and all(.[]; type == "object" and (.key | type == "string"))) and
                ((has("marker") | not) or (.marker | type == "string" and length <= 4096))' \
                "$D_TMP/page.json" >/dev/null 2>&1 || return 1
            D_candidate=$(jq -r --arg prefix "$D_prefix" --arg date "$D_date" \
                --arg cutoff "family-calendar/$D_SCREEN/${D_stamp%??????}/$D_stamp.png" '
                [.items[].key | select(startswith($prefix)) |
                 select(ltrimstr($prefix) | test("^" + $date + "([01][0-9]|2[0-3])[0-5][0-9][0-5][0-9]\\.png$")) |
                 select(. <= $cutoff)] | max // empty' "$D_TMP/page.json") || return 1
            D_newest=$(printf '%s\n%s\n' "$D_newest" "$D_candidate" | LC_ALL=C sort | tail -n 1) || return 1
            D_marker=$(jq -r '(.marker // "") | @uri' "$D_TMP/page.json") || return 1
            [ -n "$D_marker" ] || break
            if grep -Fxq "$D_marker" "$D_TMP/markers"; then return 1; fi
            printf '%s\n' "$D_marker" >> "$D_TMP/markers" || return 1
        done
        [ -z "$D_newest" ] || break
        D_day=$((D_day + 1))
    done
    [ -n "$D_newest" ] || return 1
    D_url="$D_DOMAIN/$D_newest?e=$(($(date +%s) + 300))"
    printf '%s' "$D_url" > "$D_TMP/signing" || return 1
    D_sig=$(discovery_hmac "$D_TMP/signing") || return 1
    printf 'url = "%s&token=%s:%s"\n' "$D_url" "$D_AK" "$D_sig" > "$D_OUTPUT"
}

discover_calendar() {
    D_CA=$2
    D_OUTPUT=$3
    D_TMP="${PRIVATE_DIR:-$LOCK}/discovery"
    mkdir "$D_TMP" 2>/dev/null || return 1
    # Missing system openssl.cnf is harmless for digest operations; suppress that warning.
    OPENSSL_CONF=/dev/null
    export OPENSSL_CONF
    D_result=0
    discovery_impl "$1" || D_result=1
    rm -rf "$D_TMP"
    unset D_AK D_pad D_sig D_url
    return "$D_result"
}
