#!/bin/sh

set -eu
umask 077

base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
binary=/tmp/rd05-tg-proxy
pidfile=/tmp/rd05-tg-proxy.pid
archive=/tmp/rd05-tg-proxy.tar.gz
new=/tmp/rd05-tg-proxy.new
log=/tmp/rd05-tg-proxy.log

running() {
    [ -r "$pidfile" ] || return 1
    pid=$(cat "$pidfile")
    case "$pid" in '' | *[!0-9]*) return 1 ;; esac
    [ "$pid" -gt 1 ] && kill -0 "$pid" 2> /dev/null && [ "$(readlink "/proc/$pid/exe" 2> /dev/null)" = "$binary" ]
}

if [ "${1:-start}" = stop ]; then
    if running; then
        kill "$pid" 2> /dev/null || true
        sleep 1
    fi
    rm -f "$pidfile" "$binary" "$archive" "$new"
    exit 0
fi

[ ! -e "$base/disabled" ] || exit 0
running && exit 0

if [ ! -x "$binary" ]; then
    rm -f "$archive" "$new"
    trap 'rm -f "$archive" "$new"' EXIT
    curl -fLsS --connect-timeout 10 --max-time 90 -o "$archive" 'https://github.com/valnesfjord/tg-ws-proxy-rs/releases/download/v2.7.0/tg-ws-proxy-mipsel-unknown-linux-musl-upx.tar.gz'
    [ "$(openssl dgst -sha256 "$archive" | awk '{print $NF}')" = 9887ff2afdc8a3033c98715ca0e788aab41800758ec8edc64c7306f13c90579d ]
    tar -xOzf "$archive" tg-ws-proxy > "$new"
    chmod 700 "$new"
    "$new" --version > /dev/null
    mv "$new" "$binary"
    rm -f "$archive"
    trap - EXIT
fi

[ ! -e "$base/disabled" ] || exit 0

address=$(ip -4 addr show dev br-lan | awk '/inet / {sub(/\/.*/, "", $2); print $2; exit}')
[ -n "$address" ]
export TG_SECRET=f37ff59d5946e9c1c7670a3710a099fe
(trap '' HUP; exec "$binary" --host "$address" --port 1443 --pool-size 1 --max-connections 24 --cf-domain fixtelega.co.uk --default-domains --cf-priority --no-outbound-proxy --quiet) > "$log" 2>&1 < /dev/null &
echo $! > "$pidfile"
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    running || exit 1
    if netstat -lnt | awk -v address="$address:1443" '$4 == address && $6 == "LISTEN" {found=1} END {exit !found}'; then
        exit 0
    fi
    sleep 1
done
exit 1
