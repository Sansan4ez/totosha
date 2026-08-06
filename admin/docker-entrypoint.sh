#!/bin/sh
set -e

# Read admin credentials
# User from env, password from Docker secret or env
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASSWORD_FILE="${ADMIN_PASSWORD_FILE:-/run/secrets/admin_password}"
ADMIN_API_TOKEN_FILE="${ADMIN_API_TOKEN_FILE:-/run/secrets/admin_api_token}"

# Try to read password from Docker secret first
if [ -f "$ADMIN_PASSWORD_FILE" ]; then
    ADMIN_PASSWORD=$(cat "$ADMIN_PASSWORD_FILE" | tr -d '\n')
elif [ -n "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD="$ADMIN_PASSWORD"
else
    ADMIN_PASSWORD="admin"
    echo "WARNING: Using default password 'admin'. Change it in secrets/admin_password.txt!"
fi

# Create htpasswd file guarding the panel itself.
htpasswd -bc /etc/nginx/.htpasswd "$ADMIN_USER" "$ADMIN_PASSWORD"

# The core admin API is guarded by a separate service token, which nginx injects
# into proxied /api/ requests via its env module. No fallback: an empty token
# makes core answer 401, which is the correct outcome for a missing secret.
if [ -f "$ADMIN_API_TOKEN_FILE" ]; then
    ADMIN_TOKEN=$(tr -d '\n' < "$ADMIN_API_TOKEN_FILE")
else
    ADMIN_TOKEN=""
    echo "WARNING: $ADMIN_API_TOKEN_FILE is missing; every /api/ call will fail with 401."
fi
export ADMIN_TOKEN

# Dynamic module and env directives are only valid in the main context.
if ! grep -q '^load_module modules/ngx_http_js_module.so;' /etc/nginx/nginx.conf; then
    sed -i '1iload_module modules/ngx_http_js_module.so;' /etc/nginx/nginx.conf
fi
if ! grep -q '^env ADMIN_TOKEN;' /etc/nginx/nginx.conf; then
    sed -i '1ienv ADMIN_TOKEN;' /etc/nginx/nginx.conf
fi

echo "✓ Admin panel auth configured for user: $ADMIN_USER"

# Execute the main command
exec "$@"
