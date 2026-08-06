#!/bin/bash
# Setup script for LocalTopSH
# Creates required directory structure and placeholder files

set -e

echo "🔧 Setting up LocalTopSH..."

# Machine-generated secrets below need a CSPRNG. Fail early with a clear message
# rather than letting `set -e` abort on a missing binary.
if ! command -v openssl >/dev/null 2>&1; then
  echo "❌ openssl is required to generate service secrets. Install it and re-run." >&2
  exit 1
fi

# Create directories
mkdir -p secrets workspace workspace/_shared

# Set workspace permissions for Docker containers
chmod -R 777 workspace

# Required secrets (must be filled!)
if [ ! -f secrets/telegram_token.txt ]; then
  echo "YOUR_TELEGRAM_BOT_TOKEN" > secrets/telegram_token.txt
  echo "⚠️  Created secrets/telegram_token.txt - EDIT WITH YOUR BOT TOKEN!"
fi

if [ ! -f secrets/api_key.txt ]; then
  echo "YOUR_API_KEY" > secrets/api_key.txt
  echo "⚠️  Created secrets/api_key.txt - EDIT WITH YOUR API KEY!"
fi

if [ ! -f secrets/base_url.txt ]; then
  echo "https://api.openai.com/v1" > secrets/base_url.txt
  echo "📝 Created secrets/base_url.txt with default OpenAI URL"
fi

# Optional secrets (empty = feature disabled)
if [ ! -f secrets/zai_api_key.txt ]; then
  touch secrets/zai_api_key.txt
  echo "📝 Created empty secrets/zai_api_key.txt (Z.AI search optional)"
fi

if [ ! -f secrets/gdrive_client_id.txt ]; then
  touch secrets/gdrive_client_id.txt
  echo "📝 Created empty secrets/gdrive_client_id.txt (Google Drive optional)"
fi

if [ ! -f secrets/gdrive_client_secret.txt ]; then
  touch secrets/gdrive_client_secret.txt
  echo "📝 Created empty secrets/gdrive_client_secret.txt (Google Drive optional)"
fi

# Userbot secrets (optional - only needed for userbot mode)
if [ ! -f secrets/telegram_api_id.txt ]; then
  touch secrets/telegram_api_id.txt
  echo "📝 Created empty secrets/telegram_api_id.txt (Userbot optional)"
fi

if [ ! -f secrets/telegram_api_hash.txt ]; then
  touch secrets/telegram_api_hash.txt
  echo "📝 Created empty secrets/telegram_api_hash.txt (Userbot optional)"
fi

if [ ! -f secrets/telegram_phone.txt ]; then
  touch secrets/telegram_phone.txt
  echo "📝 Created empty secrets/telegram_phone.txt (Userbot optional)"
fi

# Admin panel basic-auth password (a human types this one)
if [ ! -f secrets/admin_password.txt ]; then
  echo "changeme123" > secrets/admin_password.txt
  echo "⚠️  Created secrets/admin_password.txt with default password - CHANGE IT!"
fi

# Service token for the core admin API. Separate from the panel password so that
# compromising one boundary does not hand over the others; machine-generated, so
# there is no weak-password question.
if [ ! -f secrets/admin_api_token.txt ]; then
  openssl rand -hex 32 > secrets/admin_api_token.txt
  echo "🔑 Generated secrets/admin_api_token.txt (core admin API service token)"
fi

# Grafana admin password - its own boundary, rotated without touching the services
if [ ! -f secrets/grafana_admin_password.txt ]; then
  openssl rand -base64 24 > secrets/grafana_admin_password.txt
  echo "🔑 Generated secrets/grafana_admin_password.txt (Grafana admin login)"
fi

# Model name (optional - defaults to gpt-4.1-mini in core)
if [ ! -f secrets/model_name.txt ]; then
  touch secrets/model_name.txt
  echo "📝 Created empty secrets/model_name.txt (uses default model)"
fi

# Set permissions
chmod 700 secrets
# Docker Compose file-based secrets need to be readable inside containers.
# With secrets/ at 700, 644 is still safe on the host.
chmod 644 secrets/*.txt

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit secrets/telegram_token.txt with your bot token"
echo "2. Edit secrets/api_key.txt with your LLM API key"
echo "3. Change secrets/admin_password.txt from default 'changeme123' (admin panel login)"
echo "4. (Optional) Add Google Drive credentials for Drive integration"
echo "5. Run: docker compose up -d"
