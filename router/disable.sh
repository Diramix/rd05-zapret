#!/bin/sh

set -eu

base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

touch "$base/disabled"

if [ -r /tmp/rd05-watchdog.pid ]; then
    pid=$(cat /tmp/rd05-watchdog.pid)
    case "$pid" in
        '' | *[!0-9]*)
            exit 1
            ;;
    esac
    kill "$pid" 2> /dev/null || true
fi

sh "$base/transparent-off.sh"
echo 'Transparent processing disabled'
