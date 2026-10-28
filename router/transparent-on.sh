#!/bin/sh

set -eu

base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

sh "$base/transparent-off.sh" rules-only
trap 'sh "$base/transparent-off.sh" rules-only' EXIT
sh "$base/ipsets.sh"

if [ ! -r /tmp/rd05-transparent.pid ] || ! kill -0 "$(cat /tmp/rd05-transparent.pid)" 2> /dev/null; then
    {
        printf '%s\n' '--daemon' '--pidfile=/tmp/rd05-transparent.pid'
        sed "s|@ROOT@|$base|g" "$base/transparent.conf"
    } > /tmp/rd05-transparent-runtime.conf
    "$base/tpws" @/tmp/rd05-transparent-runtime.conf > /tmp/rd05-transparent.log 2>&1
    sleep 1
    kill -0 "$(cat /tmp/rd05-transparent.pid)"
fi

for tool in iptables ip6tables; do
    "$tool" -t nat -N RD05_TPWS
    "$tool" -t nat -A RD05_TPWS -m addrtype --dst-type LOCAL -j RETURN
    "$tool" -I INPUT 1 -i br-lan -p tcp --dport 10813 -j ACCEPT
done

for subnet in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
    iptables -t nat -A RD05_TPWS -d "$subnet" -j RETURN
done

for subnet in ::/128 ::1/128 ::ffff:0:0/96 64:ff9b::/96 100::/64 fc00::/7 fe80::/10 ff00::/8; do
    ip6tables -t nat -A RD05_TPWS -d "$subnet" -j RETURN
done

for subnet in $(ip -6 route show dev br-lan | awk '$1 ~ /\// && $1 !~ /^unreachable$/ {print $1}'); do
    ip6tables -t nat -A RD05_TPWS -d "$subnet" -j RETURN
done

iptables -t nat -A RD05_TPWS -m set --match-set RD05_EXCLUDE4 dst -j RETURN
iptables -t nat -A RD05_TPWS -p tcp -m set --match-set RD05_TARGET4 dst -j REDIRECT --to-ports 10813
ip6tables -t nat -A RD05_TPWS -m set --match-set RD05_EXCLUDE6 dst -j RETURN
ip6tables -t nat -A RD05_TPWS -p tcp -m set --match-set RD05_TARGET6 dst -j REDIRECT --to-ports 10813

for family in 4 6; do
    case "$family" in
        4)
            tool=iptables
            stun_filter='0>>22&0x3C@4>>16=28:65535&&0>>22&0x3C@12=0x2112A442&&0>>22&0x3C@8&0xC0000003=0'
            ;;
        6)
            tool=ip6tables
            stun_filter='44>>16=28:65535&&52=0x2112A442&&48&0xC0000003=0'
            ;;
    esac
    "$tool" -N RD05_QUIC
    "$tool" -A RD05_QUIC -m set --match-set "RD05_EXCLUDE$family" dst -j RETURN
    "$tool" -A RD05_QUIC -p udp -m u32 --u32 "$stun_filter" -j RETURN
    "$tool" -A RD05_QUIC -m set --match-set "RD05_TARGET$family" dst -j REJECT
    "$tool" -I FORWARD 1 -i br-lan -o eth2 -p udp --dport 443 -j RD05_QUIC
    for protocol in udp tcp; do
        "$tool" -t nat -I PREROUTING 1 -i br-lan -p "$protocol" --dport 53 -j REDIRECT --to-ports 53
    done
done

for tool in iptables ip6tables; do
    "$tool" -t nat -I PREROUTING 1 -i br-lan -p tcp -j RD05_TPWS
done

touch /tmp/rd05-transparent.active
trap - EXIT
echo "Transparent TCP processing enabled"
