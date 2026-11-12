#!/bin/sh
set -eu
umask 077
base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ ! -e "$base/disabled" ] || exit 0
mkdir /tmp/rd05-tg-standalone.lock 2>/dev/null || exit 0
trap 'rmdir /tmp/rd05-tg-standalone.lock' EXIT
[ ! -e "$base/disabled" ] || exit 0
sh "$base/proxy.sh" start
