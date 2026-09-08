#!/usr/bin/env bash
# Build a self-contained USB distribution. Existing portable user data is never replaced.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Sentinel Fork"
SOURCE_APP="${PROJECT_ROOT}/dist.noindex/${APP_NAME}.app"
OUTPUT="${1:-${PROJECT_ROOT}/dist.noindex/Sentinel Fork Portable}"
DATA_DIR="${OUTPUT}/${APP_NAME} Data"
MIN_KB=262144

cd "$PROJECT_ROOT"
echo "▸ Running portable and Beacon release checks…"
"${PROJECT_ROOT}/.venv/bin/python" -m pytest -q -p no:cacheprovider \
    tests/test_portable_runtime.py tests/test_agents_scenarios.py tests/test_ui_panels.py \
    -k 'portable or WiFiAgent or BeaconPanel'
"${PROJECT_ROOT}/scripts/build_app.sh" --skip-tests

mkdir -p "$OUTPUT"
if [ ! -w "$OUTPUT" ]; then
    echo "Error: portable destination is read-only: $OUTPUT" >&2
    exit 2
fi
AVAILABLE_KB="$(df -Pk "$OUTPUT" | awk 'NR==2 {print $4}')"
if [ -z "$AVAILABLE_KB" ] || [ "$AVAILABLE_KB" -lt "$MIN_KB" ]; then
    echo "Error: portable destination needs at least 256 MiB free." >&2
    exit 3
fi

# Upgrade only the reproducible app bundle; user-owned data remains untouched.
NEW_APP="${OUTPUT}/.${APP_NAME}.app.new"
rm -rf "$NEW_APP"
ditto "$SOURCE_APP" "$NEW_APP"
rm -rf "${OUTPUT}/${APP_NAME}.app"
mv "$NEW_APP" "${OUTPUT}/${APP_NAME}.app"

touch "${OUTPUT}/.sentinel-portable"
mkdir -p "$DATA_DIR/data/chats" "$DATA_DIR/data/logs" "$DATA_DIR/config"
if [ ! -e "$DATA_DIR/.env" ]; then
    cp "${PROJECT_ROOT}/.env.example" "$DATA_DIR/.env"
fi
cp "${PROJECT_ROOT}/docs/portable_mode.md" "${OUTPUT}/Portable Read Me.md"
cp "${PROJECT_ROOT}/scripts/run_portable.command" "${OUTPUT}/Start Sentinel Fork.command"
chmod +x "${OUTPUT}/Start Sentinel Fork.command"

echo "Built/updated portable distribution: $OUTPUT"
echo "User data preserved at: $DATA_DIR"
echo "No project .env or API secrets were copied."
