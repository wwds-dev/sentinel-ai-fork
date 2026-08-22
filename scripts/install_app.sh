#!/usr/bin/env bash
# Install "Sentinel Fork.app" into /Applications — a thin launcher that runs the
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
APP_NAME="Sentinel Fork"
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

# The launcher must not background python: the applet is the parent process, and
# macOS reaps the child as soon as the parent returns. Blocking on `do shell
# script` keeps the applet alive as the visible app for the GUI's lifetime.
#
# Two details that matter:
#  * Missing venv/main.py is reported up front, so a broken install says why
#    instead of bouncing the icon once and giving up.
#  * The command ends in "; exit 0" so python's exit status never reaches
#    AppleScript. Otherwise quitting or killing the app returns non-zero, which
#    AppleScript raises as an error dialog — that left the applet alive with no
#    window, and macOS then treated the app as running and refused to relaunch.
cat > "$STAGE/launch.applescript" <<APPLESCRIPT
set pythonBin to "${PY}"
set mainPy to "${PROJECT_ROOT}/main.py"
if (do shell script "[ -x " & quoted form of pythonBin & " ] && [ -f " & quoted form of mainPy & " ] && echo ok || echo missing") is not "ok" then
    display alert "Sentinel Fork cannot start" message "The project is not where the app expects it:" & return & return & "${PROJECT_ROOT}" & return & return & "Re-run scripts/install_app.sh from the project." as critical
    return
end if
do shell script "cd " & quoted form of "${PROJECT_ROOT}" & " && " & quoted form of pythonBin & " " & quoted form of mainPy & " > /tmp/sentinel_fork_launch.log 2>&1; exit 0"
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
defaults write "$APP_DIR/Contents/Info" CFBundleIdentifier -string "com.netrunner3000.sentinel.fork"
defaults write "$APP_DIR/Contents/Info" LSUIElement -bool false
plutil -convert xml1 "$APP_DIR/Contents/Info.plist"

# Stop a running copy so Launch Services picks up the new bundle.
pkill -f "${PROJECT_ROOT}/main.py" 2>/dev/null || true
sleep 1

rm -rf "$INSTALLED"
cp -R "$APP_DIR" "$INSTALLED"
xattr -cr "$INSTALLED" 2>/dev/null || true
codesign --force --deep --sign - "$INSTALLED"

LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
"$LSREG" -f "$INSTALLED"

echo ""
echo "✓ Installed: ${INSTALLED}"
echo "  Runs live from: ${PROJECT_ROOT}"
echo "  Edit the code, relaunch the app — no rebuild."
echo "  API keys: ${PROJECT_ROOT}/.env"
