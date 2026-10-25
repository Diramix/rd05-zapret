#!/bin/sh

set -eu

base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

rm -f "$base/disabled"
sh "$base/ensure.sh"
