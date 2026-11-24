#!/bin/sh
# timed.sh OUT CMD... — выполнить команду и записать время в секундах в OUT (для сводки CI).
set -eu
out=$1
shift
start=$(date +%s)
"$@"
echo $(( $(date +%s) - start )) > "$out"
