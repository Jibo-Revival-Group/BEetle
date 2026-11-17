#!/bin/sh
# Opens BEetle against a stand-in robot: real BEacon page on 127.0.0.1:8123 and a fake SSH Jibo,
# then checks the page took BEep's look, the Store tab followed, and a conversion finished.
# usage: ci/app-check.sh <BEam beacon/public dir>   (Linux needs a display, e.g. xvfb-run)
set -e
cd "$(dirname "$0")/.."
RUN=$(mktemp -d)
python3 ci/fake-beacon.py "$1" > "$RUN/beacon.log" 2>&1 & B=$!
node ci/fake-jibo-ssh.js 2222 "$RUN" > "$RUN/ssh.log" 2>&1 & S=$!
trap 'kill $B $S 2>/dev/null' EXIT
sleep 2
export BEETLE_CHECK_SSH_PORT=2222 BEETLE_CHECK_PM='echo Installing 5x1; echo Rebooting now'
OUT=$(timeout 120 npx electron . --check --no-sandbox --user-data-dir="$RUN/profile" 2>&1 || true)
echo "$OUT" | grep BEETLE_CHECK || { echo "$OUT" | tail -40; exit 1; }
echo "$OUT" | grep -q '"ok":true'
echo "$OUT" | grep BEETLE_CHECK | grep -q 'rgb(17, 21, 19)' # BEep's backdrop #111513
echo "app check passed"
