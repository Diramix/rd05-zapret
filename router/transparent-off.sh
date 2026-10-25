#!/bin/sh

for tool in iptables ip6tables; do
    "$tool" -t nat -D PREROUTING -i br-lan -p tcp -j RD05_TPWS 2> /dev/null
    "$tool" -t nat -F RD05_TPWS 2> /dev/null
    "$tool" -t nat -X RD05_TPWS 2> /dev/null
    "$tool" -D FORWARD -i br-lan -o eth2 -p udp --dport 443 -j REJECT 2> /dev/null
    "$tool" -D FORWARD -i br-lan -o eth2 -p udp --dport 443 -j RD05_QUIC 2> /dev/null
    "$tool" -F RD05_QUIC 2> /dev/null
    "$tool" -X RD05_QUIC 2> /dev/null
    for protocol in udp tcp; do
        "$tool" -t nat -D PREROUTING -i br-lan -p "$protocol" --dport 53 -j REDIRECT --to-ports 53 2> /dev/null
    done
    "$tool" -D INPUT -i br-lan -p tcp --dport 10813 -j ACCEPT 2> /dev/null
done

rm -f /tmp/rd05-transparent.active

if [ "${1:-}" != rules-only ] && [ -r /tmp/rd05-transparent.pid ]; then
    pid=$(cat /tmp/rd05-transparent.pid)
    case "$pid" in
        '' | *[!0-9]*)
            exit 1
            ;;
    esac
    case "$(readlink "/proc/$pid/exe" 2> /dev/null)" in
        */tpws)
            kill "$pid" 2> /dev/null
            ;;
    esac
    rm -f /tmp/rd05-transparent.pid
fi

if [ "${1:-}" != rules-only ] && [ -r /tmp/rd05-seed.pid ]; then
    kill "$(cat /tmp/rd05-seed.pid)" 2> /dev/null
    rm -f /tmp/rd05-seed.pid
fi

if [ "${1:-}" != rules-only ] && [ -f /tmp/dnsmasq.d/rd05-zapret.conf ]; then
    rm -f /tmp/dnsmasq.d/rd05-zapret.conf /tmp/rd05-ipsets.signature
    /etc/init.d/dnsmasq restart > /dev/null 2>&1
fi

exit 0
