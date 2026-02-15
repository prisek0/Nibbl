#!/bin/bash
# Uninstall the Nibbl LaunchAgent.

set -euo pipefail

PLIST_NAME="com.nibbl.agent"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"

if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm "$PLIST_PATH"
    echo "LaunchAgent removed: $PLIST_PATH"
else
    echo "LaunchAgent not found at $PLIST_PATH"
fi
