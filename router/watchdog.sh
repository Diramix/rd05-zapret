#!/bin/sh

base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

echo $$ > /tmp/rd05-watchdog.pid
trap 'rm -f /tmp/rd05-watchdog.pid' EXIT

while [ ! -e "$base/disabled" ]; do
    pid=$(cat /tmp/rd05-transparent.pid 2> /dev/null)
    case "$pid" in
        '' | *[!0-9]*)
            pid=0
            ;;
    esac
    if [ "$pid" -le 1 ] || ! kill -0 "$pid" 2> /dev/null; then
        sh "$base/transparent-off.sh" rules-only
        exit 0
    fi
    available=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
    if [ "$available" -lt 6000 ]; then
        sh "$base/transparent-off.sh"
        exit 0
    fi
    sleep 3
done
