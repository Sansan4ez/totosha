#!/bin/bash
# Entrypoint for core container
# Ensures workspace directory has correct permissions

echo "🔧 Initializing workspace permissions..."

# Ensure workspace directories exist with correct permissions
mkdir -p /workspace/_shared 2>/dev/null || true
chmod 777 /workspace 2>/dev/null || true
chmod 777 /workspace/_shared 2>/dev/null || true

# Ensure _shared files are writable
if [ -f /workspace/_shared/admin_config.json ]; then
    chmod 666 /workspace/_shared/admin_config.json 2>/dev/null || true
fi

check_workspace_writable() {
    local path="$1"
    local probe="${path}/.write-probe-$$"
    if ! touch "${probe}" 2>/dev/null; then
        echo "❌ Workspace path is not writable: ${path}"
        echo "   Fix host bind mount permissions, for example:"
        echo "   chmod 777 workspace workspace/_shared"
        exit 1
    fi
    rm -f "${probe}" 2>/dev/null || true
}

check_workspace_writable /workspace
check_workspace_writable /workspace/_shared

echo "✅ Workspace ready"

# Start the application
exec python -u main.py
