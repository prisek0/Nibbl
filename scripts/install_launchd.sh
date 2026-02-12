#!/bin/bash
# Install FoodAgend as a macOS LaunchAgent (auto-start on login, restart on crash).
#
# Usage: bash scripts/install_launchd.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_NAME="com.foodagend.agent"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"

# Check virtualenv exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Python venv not found at $VENV_PYTHON"
    echo "Create it first: python3 -m venv .venv && .venv/bin/pip install -e ."
    exit 1
fi

# Create log directory
mkdir -p "${PROJECT_DIR}/logs"

# Write plist
cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_PYTHON}</string>
        <string>-m</string>
        <string>src.main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/logs/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/logs/stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>FOODAGEND_CONFIG</key>
        <string>${PROJECT_DIR}/config.toml</string>
    </dict>
</dict>
</plist>
PLIST

echo "Installed LaunchAgent at: $PLIST_PATH"
echo ""
echo "To start now:  launchctl load $PLIST_PATH"
echo "To stop:       launchctl unload $PLIST_PATH"
echo "To view logs:  tail -f ${PROJECT_DIR}/logs/stdout.log"
echo ""
echo "NOTE: Make sure your .env vars are set in your shell profile,"
echo "or add them to the plist EnvironmentVariables section."
