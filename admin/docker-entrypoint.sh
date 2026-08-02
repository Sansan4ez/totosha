#!/bin/sh
set -e

# Read admin credentials
# User from env, password from Docker secret or env
ADMIN_USER="${ADMIN_USER:-admin}"

# Try to read password from Docker secret first
if [ -f "$ADMIN_PASSWORD_FILE" ]; then
    ADMIN_PASSWORD=$(cat "$ADMIN_PASSWORD_FILE" | tr -d '\n')
elif [ -n "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD="$ADMIN_PASSWORD"
else
    ADMIN_PASSWORD="admin"
    echo "WARNING: Using default password 'admin'. Change it in secrets/admin_password.txt!"
fi

# Create htpasswd file and expose the same secret to nginx via its env module.
htpasswd -bc /etc/nginx/.htpasswd "$ADMIN_USER" "$ADMIN_PASSWORD"
export ADMIN_TOKEN="$ADMIN_PASSWORD"

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
