#!/bin/bash
set -euo pipefail

APP_USER=app
APP_GROUP=app
CREDS_DIR="${GOOGLE_MCP_CREDENTIALS_DIR:-/app/store_creds}"

ensure_creds_dir_permissions() {
    mkdir -p "$CREDS_DIR"

    if [ "$(id -u)" -ne 0 ]; then
        return
    fi

    chown -R "$APP_USER:$APP_GROUP" "$CREDS_DIR"
    chmod 755 "$CREDS_DIR"
}

# Read secrets from Docker secrets files and export as env vars
if [ -f /run/secrets/gdrive_client_id ]; then
    export GOOGLE_OAUTH_CLIENT_ID=$(cat /run/secrets/gdrive_client_id)
fi

if [ -f /run/secrets/gdrive_client_secret ]; then
    export GOOGLE_OAUTH_CLIENT_SECRET=$(cat /run/secrets/gdrive_client_secret)
fi

ensure_creds_dir_permissions

# Start the MCP server
if [ "$(id -u)" -eq 0 ]; then
    exec gosu "$APP_USER:$APP_GROUP" uv run main.py --transport streamable-http ${TOOL_TIER:+--tool-tier "$TOOL_TIER"} ${TOOLS:+--tools $TOOLS}
fi

exec uv run main.py --transport streamable-http ${TOOL_TIER:+--tool-tier "$TOOL_TIER"} ${TOOLS:+--tools $TOOLS}
