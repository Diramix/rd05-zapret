#!/bin/sh

set -eu

base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

fragment=/tmp/dnsmasq.d/rd05-zapret.conf
stamp=/tmp/rd05-ipsets.signature
signature=$({ md5sum "$base/transparent.conf" "$base/ipsets.sh" "$base/seed.sh" "$base/lists"/*.txt; } | md5sum | awk '{print $1}')
ready=1

for set in RD05_TARGET4 RD05_TARGET6 RD05_EXCLUDE4 RD05_EXCLUDE6; do
    ipset list "$set" > /dev/null 2>&1 || ready=0
done

if [ "$ready" = 1 ] && [ -r "$fragment" ] && [ -r "$stamp" ] && [ "$(cat "$stamp")" = "$signature" ]; then
    sh "$base/seed.sh" start
    exit 0
fi

for family in 4 6; do
    case "$family" in
        4)
            protocol=inet
            ;;
        6)
            protocol=inet6
            ;;
    esac
    for role in TARGET EXCLUDE; do
        ipset create "RD05_${role}${family}" hash:net family "$protocol" timeout 86400 maxelem 16384 -exist
    done
done

include=/tmp/rd05-domains.include

list_files() {
    awk -F= -v option="$1" -v base="$base" '$1==option {gsub(/@ROOT@/,base,$2); print $2}' "$base/transparent.conf"
}

{
    for file in $(list_files --hostlist); do
        cat "$file"
    done
    awk -F= '/^--hostlist-domains=/ {n=split($2,domains,","); for(i=1;i<=n;i++) print domains[i]}' "$base/transparent.conf"
} | awk '{sub(/#.*/, ""); gsub(/\r/, ""); if(NF) print $1}' | LC_ALL=C sort -u > "$include"

mkdir -p /tmp/dnsmasq.d
new=/tmp/rd05-dnsmasq.new
{
    while IFS= read -r domain; do
        printf 'ipset=/%s/RD05_TARGET4,RD05_TARGET6\n' "$domain"
    done < "$include"
} > "$new"
dnsmasq --test --conf-file="$new" > /dev/null 2>&1

for set in RD05_TARGET4 RD05_TARGET6 RD05_EXCLUDE4 RD05_EXCLUDE6; do
    ipset flush "$set"
done

for role in TARGET EXCLUDE; do
    case "$role" in
        TARGET)
            files=$(list_files --ipset)
            ;;
        EXCLUDE)
            files=$(list_files --ipset-exclude)
            ;;
    esac
    for file in $files; do
        while IFS= read -r subnet || [ -n "$subnet" ]; do
            subnet=${subnet%%#*}
            [ -n "$subnet" ] || continue
            case "$subnet" in
                *:*)
                    family=6
                    ;;
                *)
                    family=4
                    ;;
            esac
            ipset add "RD05_${role}${family}" "$subnet" timeout 0 -exist
        done < "$file"
    done
done

mv "$new" "$fragment"
/etc/init.d/dnsmasq restart > /tmp/rd05-dnsmasq-restart.log 2>&1
printf '%s\n' "$signature" > "$stamp"
rm -f /tmp/rd05-seed.updated
sh "$base/seed.sh" start
echo 'Selective IPv4/IPv6 destination sets updated'
