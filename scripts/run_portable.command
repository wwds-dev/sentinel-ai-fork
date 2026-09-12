#!/usr/bin/env bash
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP="$ROOT/Sentinel.app"
DATA="$ROOT/Sentinel Data"

fail() {
    osascript \
        -e 'on run argv' \
        -e 'display alert "Sentinel cannot start" message (item 1 of argv) as critical' \
        -e 'end run' -- "$1" 2>/dev/null || echo "Error: $1" >&2
    exit 1
}

[ -d "$APP" ] || fail "The portable app is missing from $ROOT. Rebuild or restore the app bundle."
[ -f "$ROOT/.sentinel-portable" ] || fail "The portable marker is missing. Use the complete portable distribution."
mkdir -p "$DATA" 2>/dev/null || fail "The USB volume is read-only, unavailable, or has been ejected."
[ -w "$DATA" ] || fail "The portable data folder is not writable: $DATA"
AVAILABLE_KB="$(df -Pk "$ROOT" 2>/dev/null | awk 'NR==2 {print $4}')"
[ -n "$AVAILABLE_KB" ] || fail "The USB volume is unavailable or has been ejected."
[ "$AVAILABLE_KB" -ge 262144 ] || fail "The USB volume has less than 256 MiB free. Free space before starting."

export SENTINEL_PORTABLE_ROOT="$ROOT"
"$APP/Contents/MacOS/Sentinel" > "$DATA/data/portable-launch.log" 2>&1
STATUS=$?
if [ "$STATUS" -ne 0 ]; then
    fail "Sentinel stopped unexpectedly. See Sentinel Data/data/portable-launch.log."
fi
