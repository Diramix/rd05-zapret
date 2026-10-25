#!/bin/sh

set -eu

base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

pidfile=/tmp/rd05-seed.pid
stamp=/tmp/rd05-seed.updated

if [ "${1:-start}" = start ]; then
    if [ -r "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2> /dev/null; then
        exit 0
    fi
    now=$(date +%s)
    if [ -r "$stamp" ] && [ "$((now - $(cat "$stamp")))" -lt 3600 ]; then
        exit 0
    fi
    trap '' HUP
    sh "$base/seed.sh" run < /dev/null > /tmp/rd05-dns-seed.log 2>&1 &
    echo $! > "$pidfile"
    exit 0
fi

trap 'rm -f "$pidfile"' EXIT
sleep 2

for attempt in 1 2 3 4 5; do
    if nslookup www.youtube.com 127.0.0.1 > /dev/null 2>&1; then
        break
    fi
    sleep 2
done

seed() {
    role=$1
    domain=$2
    [ ! -e "$base/disabled" ] || exit 0
    nslookup "$domain" 127.0.0.1 > /dev/null 2>&1 || true
    response=$(curl --resolve cloudflare-dns.com:443:1.1.1.1 --max-time 4 -fsS -H 'accept: application/dns-json' "https://cloudflare-dns.com/dns-query?name=$domain&type=AAAA" 2> /dev/null || true)
    for address in $(printf '%s' "$response" | jsonfilter -e '@.Answer[*].data' 2> /dev/null); do
        case "$address" in
            *:*)
                ipset add "RD05_${role}6" "$address" timeout 86400 -exist
                ;;
        esac
    done
}

for domain in youtubei.googleapis.com www.youtube.com youtube.com discord.com gateway.discord.gg cdn.discordapp.com media.discordapp.net discord.gg discordapp.com discordapp.net discord.media www.speedtest.net results.speedtest.net speedtest-univ-results-api.speedtest.net x.com twitter.com api.x.com api.twitter.com t.co abs.twimg.com pbs.twimg.com video.twimg.com; do
    if awk -v domain="$domain" '
        $0 == domain || (length(domain) > length($0) && substr(domain, length(domain) - length($0)) == "." $0) {found = 1; exit}
        END {exit !found}
    ' /tmp/rd05-domains.include; then
        seed TARGET "$domain"
    fi
done

while IFS= read -r domain; do
    seed TARGET "$domain"
done < /tmp/rd05-domains.include
date +%s > "$stamp"
