#!/bin/sh

set -eu

base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

[ ! -e "$base/disabled" ] || exit 0
mkdir /tmp/rd05-ensure.lock 2> /dev/null || exit 0
trap 'rmdir /tmp/rd05-ensure.lock' EXIT
running=0

if [ -r /tmp/rd05-transparent.pid ]; then
    pid=$(cat /tmp/rd05-transparent.pid)
    case "$pid" in
        '' | *[!0-9]*)
            pid=0
            ;;
    esac
    if [ "$pid" -gt 1 ] && kill -0 "$pid" 2> /dev/null && [ "$(readlink "/proc/$pid/exe" 2> /dev/null)" = "$base/tpws" ]; then
        running=1
    fi
fi

if [ "$running" = 0 ]; then
    available=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
    [ "$available" -ge 12000 ] || exit 0
    rm -f /tmp/rd05-transparent.pid
fi

sh "$base/ipsets.sh"

rules_ready() {
    for family in 4 6; do
        case "$family" in
            4)
                tool=iptables
                ;;
            6)
                tool=ip6tables
                ;;
        esac
        "$tool" -t nat -C PREROUTING -i br-lan -p tcp -j RD05_TPWS 2> /dev/null || return 1
        "$tool" -t nat -C RD05_TPWS -p tcp -m set --match-set "RD05_TARGET$family" dst -j REDIRECT --to-ports 10813 2> /dev/null || return 1
        "$tool" -t nat -C PREROUTING -i br-lan -p udp --dport 53 -j REDIRECT --to-ports 53 2> /dev/null || return 1
        "$tool" -C FORWARD -i br-lan -o eth2 -p udp --dport 443 -j RD05_QUIC 2> /dev/null || return 1
    done
    return 0
}

if [ "$running" = 0 ] || ! rules_ready; then
    sh "$base/transparent-on.sh"
fi

if [ -r /tmp/rd05-watchdog.pid ] && kill -0 "$(cat /tmp/rd05-watchdog.pid)" 2> /dev/null; then
    exit 0
fi

trap '' HUP
sh "$base/watchdog.sh" < /dev/null > /tmp/rd05-watchdog.log 2>&1 &
