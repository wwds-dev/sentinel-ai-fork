#!/usr/bin/env bash
# Install "Sentinel.app" into /Applications — a thin launcher that runs the
# project's own main.py through the project's .venv.
#
#   ./scripts/install_app.sh
#
# RUN THIS ONCE. The bundle contains no application code, only a launcher, so
# edits to main.py (or anything else in the project) are live on the next launch
# — no rebuild step. Re-run this only if the icon, the bundle identity, or the
# launcher itself changes, or if the project moves to a different path.
#
# Trade-off vs. the old PyInstaller build: the app now depends on this project
# folder and its .venv staying where they are. Moving or deleting either breaks
# the launcher (it reports the missing path instead of failing silently).
#
# Data lives in the project (data/, config/, .env) exactly as it does when you
# run `python main.py` by hand, so the app and the terminal share one state.
#
# Built as a compiled AppleScript applet rather than a shell-script bundle:
# macOS treats applets as a normal app type, while an unsigned shell-script
# CFBundleExecutable gets killed silently by Gatekeeper on launch.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Sentinel"
INSTALLED="/Applications/${APP_NAME}.app"
PY="${PROJECT_ROOT}/.venv/bin/python"

if [ ! -x "$PY" ]; then
    echo "Error: no interpreter at ${PY}" >&2
    echo "Create it first:  uv venv && uv pip install -r requirements.txt" >&2
    exit 1
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
APP_DIR="$STAGE/${APP_NAME}.app"

# The applet is only a launch shim. It must return immediately after starting
# Python; holding `do shell script` open for the full GUI lifetime makes macOS
# label the applet "Not Responding" and prevents a second click from reaching
# Sentinel's single-instance handoff. A transient launchctl job makes macOS the
# Python process owner, so the applet can exit without taking Sentinel with it.
#
# Three details that matter:
#  * Missing venv/main.py is reported up front, so a broken install says why
#    instead of bouncing the icon once and giving up.
#  * A later Python exit can never surface as an AppleScript error dialog.
#  * Every launch starts a short-lived Python process; if Sentinel is already
#    open, its local-socket guard raises that window and the new process exits.
cat > "$STAGE/launch.applescript" <<APPLESCRIPT
set pythonBin to "${PY}"
set mainPy to "${PROJECT_ROOT}/main.py"
if (do shell script "[ -x " & quoted form of pythonBin & " ] && [ -f " & quoted form of mainPy & " ] && echo ok || echo missing") is not "ok" then
    display alert "Sentinel cannot start" message "The project is not where the app expects it:" & return & return & "${PROJECT_ROOT}" & return & return & "Re-run scripts/install_app.sh from the project." as critical
    return
end if
set launchLabel to "com.netrunner3000.sentinel.launch." & (random number from 100000 to 999999)
set launchCommand to "cd " & quoted form of "${PROJECT_ROOT}" & " && exec " & quoted form of pythonBin & " " & quoted form of mainPy
do shell script "/bin/launchctl submit -l " & quoted form of launchLabel & " -o /tmp/sentinel-launch.log -e /tmp/sentinel-launch.log -- /bin/sh -c " & quoted form of launchCommand
APPLESCRIPT

osacompile -o "$APP_DIR" "$STAGE/launch.applescript"

cp "$PROJECT_ROOT/assets/icon.icns" "$APP_DIR/Contents/Resources/applet.icns"

# osacompile also emits Assets.car, an asset catalog holding the stock
# AppleScript applet artwork (the scroll-on-a-folder). macOS resolves an app's
# icon from the asset catalog BEFORE CFBundleIconFile, so leaving it in place
# silently overrides the Sentinel icon we just copied in. Drop it — the applet
# has no UI of its own that needs those assets.
rm -f "$APP_DIR/Contents/Resources/Assets.car"
defaults write "$APP_DIR/Contents/Info" CFBundleName -string "${APP_NAME}"
defaults write "$APP_DIR/Contents/Info" CFBundleDisplayName -string "${APP_NAME}"
defaults write "$APP_DIR/Contents/Info" CFBundleIdentifier -string "com.netrunner3000.sentinel"
defaults write "$APP_DIR/Contents/Info" LSUIElement -bool false
plutil -convert xml1 "$APP_DIR/Contents/Info.plist"

# Stop a running copy so Launch Services picks up the new bundle.
pkill -f "${PROJECT_ROOT}/main.py" 2>/dev/null || true
pkill -f "${INSTALLED}/Contents/MacOS/applet" 2>/dev/null || true
pkill -f "sh -c cd '${PROJECT_ROOT}'" 2>/dev/null || true
sleep 1

rm -rf "$INSTALLED"
LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
LEGACY_INSTALLED="/Applications/Sentinel Fork.app"
if [ -d "$LEGACY_INSTALLED" ]; then
    "$LSREG" -u "$LEGACY_INSTALLED" 2>/dev/null || true
    rm -rf "$LEGACY_INSTALLED"
fi

# Preserve the predecessor's packaged-app state under the final product name.
# Sentinel AI is intentionally not a migration source: it is a separate,
# archived application and must remain untouched.
LEGACY_SUPPORT="${HOME}/Library/Application Support/Sentinel Fork"
CURRENT_SUPPORT="${HOME}/Library/Application Support/Sentinel"
if [ -d "$LEGACY_SUPPORT" ] && [ ! -e "$CURRENT_SUPPORT" ]; then
    mv "$LEGACY_SUPPORT" "$CURRENT_SUPPORT"
    echo "  Migrated app data: ${LEGACY_SUPPORT} → ${CURRENT_SUPPORT}"
elif [ -d "$LEGACY_SUPPORT" ] && [ -e "$CURRENT_SUPPORT" ]; then
    echo "  Kept both app-data folders because Sentinel already exists; no automatic merge was attempted." >&2
fi
cp -R "$APP_DIR" "$INSTALLED"
xattr -cr "$INSTALLED" 2>/dev/null || true
codesign --force --deep --sign - "$INSTALLED"

"$LSREG" -f "$INSTALLED"

echo ""
echo "✓ Installed: ${INSTALLED}"
echo "  Runs live from: ${PROJECT_ROOT}"
echo "  Edit the code, relaunch the app — no rebuild."
echo "  API keys: ${PROJECT_ROOT}/.env"
