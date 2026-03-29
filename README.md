# 🐧 Topsha Local AI Agent for simple every day tasks

**AI Agent Framework for Self-Hosted LLMs — deploy on your infrastructure, keep data private.**

> 🎯 **Built for companies and developers who need:**
> - 100% on-premise AI agents (no data leaves your network)
> - Any OpenAI-compatible LLM (vLLM, Ollama, llama.cpp, text-generation-webui)
> - Production-ready security (battle-tested by 1500+ hackers)
> - Simple deployment (`docker compose up` and you're done)

---

## Why LocalTopSH?

### 🏠 100% Self-Hosted

Unlike cloud-dependent solutions, LocalTopSH runs entirely on your infrastructure:

| Problem | Cloud Solutions | LocalTopSH |
|---------|-----------------|------------|
| **Data Privacy** | Data sent to external APIs | ✅ Everything stays on-premise |
| **Compliance** | Hard to audit | ✅ Full control, easy audit |
| **API Access** | Need OpenAI/Anthropic account | ✅ Any OpenAI-compatible endpoint |
| **Sanctions/Restrictions** | Blocked in some regions | ✅ Works anywhere |
| **Cost at Scale** | $0.01-0.03 per 1K tokens | ✅ Only electricity costs |

### 🤖 Supported LLM Backends

| Backend | Example Models | Setup |
|---------|----------------|-------|
| **vLLM** | gpt-oss-120b, Qwen-72B, Llama-3-70B | `vllm serve model --api-key dummy` |
| **Ollama** | Llama 3, Mistral, Qwen, 100+ models | `ollama serve` |
| **llama.cpp** | Any GGUF model | `llama-server -m model.gguf` |
| **text-generation-webui** | Any HuggingFace model | Enable OpenAI API extension |
| **LocalAI** | Multiple backends | Docker compose included |
| **LM Studio** | Desktop-friendly | Built-in server mode |

### 💰 Cost Comparison (1M tokens/day)

| Solution | Daily Cost | Monthly Cost |
|----------|------------|--------------|
| OpenAI GPT-4 | ~$30 | ~$900 |
| Anthropic Claude | ~$15 | ~$450 |
| **Self-hosted (LocalTopSH)** | Electricity only | ~$50-100 (GPU power) |

### 🌍 Works Everywhere

- ✅ **Russia, Belarus, Iran** — sanctions don't apply to self-hosted
- ✅ **China** — no Great Firewall issues
- ✅ **Air-gapped networks** — zero internet required
- ✅ **On-premise data centers** — full compliance

---

## Quick Start

### 1. Start your LLM backend

```bash
# Option A: vLLM (recommended for production)
vllm serve gpt-oss-120b --api-key dummy --port 8000

# Option B: Ollama (easy setup)
ollama serve  # Default port 11434

# Option C: llama.cpp (minimal resources)
llama-server -m your-model.gguf --port 8000
```

### 2. Configure LocalTopSH

```bash
git clone https://github.com/vakovalskii/topsha
cd topsha

# Run setup script (creates directories with correct permissions)
./setup.sh

# Edit secrets with your credentials
nano secrets/telegram_token.txt  # Your bot token from @BotFather
nano secrets/base_url.txt        # http://your-llm-server:8000/v1
nano secrets/api_key.txt          # Your API key (or "dummy" if not needed)
nano secrets/model_name.txt       # Model name (e.g. gpt-oss-120b)
nano secrets/zai_api_key.txt      # Z.AI search key (optional)
```

**Alternative (manual setup):**

```bash
# Create directories
mkdir -p secrets workspace workspace/_shared
chmod -R 777 workspace  # Important: Docker containers need write access

# Create secrets
echo "your-telegram-token" > secrets/telegram_token.txt
echo "http://your-llm-server:8000/v1" > secrets/base_url.txt
echo "dummy" > secrets/api_key.txt
echo "changeme123" > secrets/admin_password.txt
chmod 600 secrets/*.txt
```

### 3. Deploy

```bash
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f
```

### 4. Access

- **Telegram Bot**: Message your bot
- **Admin Panel**: http://localhost:3000 (login: admin / password from `secrets/admin_password.txt`)
- **API**: http://localhost:4000/api

### 5. Configure Admin Panel Auth (Important!)

```bash
# Change default admin password (REQUIRED for production!)
echo "your-secure-password" > secrets/admin_password.txt

# Optionally change admin username via environment variable
# Edit docker-compose.yml and set ADMIN_USER=your_username

# Rebuild admin container
docker compose up -d --build admin
```

> ⚠️ **Default credentials: admin / changeme123** — change them before exposing to network!

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           YOUR INFRASTRUCTURE                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────────────────┐│
│  │   Telegram      │     │   LocalTopSH    │     │   Your LLM Backend          ││
│  │   (optional)    │────▶│   Agent Stack   │────▶│   ────────────────────────  ││
│  └─────────────────┘     │                 │     │   vLLM / Ollama / llama.cpp ││
│                          │  ┌───────────┐  │     │   gpt-oss-120b              ││
│  ┌─────────────────┐     │  │   core    │  │     │   Qwen-72B                  ││
│  │   Admin Panel   │────▶│  │  (agent)  │  │     │   Llama-3-70B               ││
│  │   :3000         │     │  └───────────┘  │     │   Mistral-22B               ││
│  └─────────────────┘     │        │        │     │   Your fine-tuned model     ││
│                          │        ▼        │     └─────────────────────────────┘│
│                          │  ┌───────────┐  │                                    │
│                          │  │  sandbox  │  │     No data leaves your network!  │
│                          │  │ (per-user)│  │                                    │
│                          │  └───────────┘  │                                    │
│                          └─────────────────┘                                    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Security (Battle-Tested)

> 🔥 **Stress-tested by 1500+ hackers** in [@neuraldeepchat](https://t.me/neuraldeepchat)
> 
> Attack attempts: Token extraction, RAM exhaustion, container escapes
> 
> **Result: 0 secrets leaked, 0 downtime**

### Five Layers of Protection

| Layer | Protection | Details |
|-------|------------|---------|
| **Access Control** | DM Policy | admin/allowlist/pairing/public modes |
| **Input Validation** | Blocked patterns | 247 dangerous commands blocked |
| **Injection Defense** | Pattern matching | 19 prompt injection patterns |
| **Sandbox Isolation** | Docker per-user | 512MB RAM, 50% CPU, 100 PIDs |
| **Secrets Protection** | Proxy architecture | Agent never sees API keys |

### Security Audit

```bash
# Run security doctor (46 checks)
python scripts/doctor.py

# Run E2E tests (10 checks)
python scripts/e2e_test.py --verbose
```

### Bench (Golden Dataset)

Run a deterministic quality check suite based on `docs/questions.md`:

```bash
python3 scripts/bench_run.py --docker-exec --limit 5
python3 scripts/bench_eval.py --results bench/results/<run_id>.jsonl
```

Runbook: `docs/operations/bench-runbook.md` (runner) and `docs/operations/bench-eval.md` (eval).

Local dashboard:

```bash
python3 scripts/bench_dashboard_build.py
python3 -m http.server 8000
# open http://127.0.0.1:8000/bench/dashboard/
```

System prompt source of truth is `core/src/agent/system.txt` in the repo. Changes made from the Admin UI modify the prompt only inside the running `core` container and are intentionally ephemeral: they do not update the repository and are lost after container recreation or rebuild.

---

## Features

### 💻 Agent Capabilities

| Category | Features |
|----------|----------|
| **System** | Shell execution, file operations, code execution |
| **Web** | Search (Z.AI), page fetching, link extraction |
| **Memory** | Persistent notes, task management, chat history |
| **Automation** | Scheduled tasks, background jobs |
| **Telegram** | Send files, DMs, message management |

### 🔧 Extensibility

| Feature | Description |
|---------|-------------|
| **Skills** | Anthropic-compatible skill packages |
| **MCP** | Model Context Protocol for external tools |
| **Tools API** | Dynamic tool loading and management |
| **Admin Panel** | Web UI for configuration and monitoring |

### 📦 Services

| Container | Port | Role |
|-----------|------|------|
| **core** | 4000 | ReAct Agent, security, sandbox orchestration |
| **bot** | 4001 | Telegram Bot (aiogram) |
| **proxy** | 3200 | Secrets isolation, LLM proxy |
| **tools-api** | 8100 | Tool registry, MCP, skills |
| **admin** | 3000 | Web admin panel (React) |
| **sandbox_{id}** | 5000-5999 | Per-user isolated execution |

---

## Configuration

### Secrets

| Secret | Required | Description |
|--------|----------|-------------|
| `telegram_token.txt` | ✅ | Bot token from @BotFather |
| `base_url.txt` | ✅ | LLM API URL (e.g. `http://vllm:8000/v1`) |
| `api_key.txt` | ✅ | LLM API key (use `dummy` if not required) |
| `model_name.txt` | ✅ | Model name (e.g. `gpt-oss-120b`) |
| `zai_api_key.txt` | ✅ | Z.AI search key |
| `admin_password.txt` | ✅ | Admin panel password (default: `changeme123`) |

### Environment Examples

#### vLLM

```bash
echo "http://vllm-server:8000/v1" > secrets/base_url.txt
echo "dummy" > secrets/api_key.txt
echo "gpt-oss-120b" > secrets/model_name.txt
```

#### Ollama

```bash
echo "http://ollama:11434/v1" > secrets/base_url.txt
echo "ollama" > secrets/api_key.txt
echo "llama3:70b" > secrets/model_name.txt
```

#### OpenAI-compatible (any)

```bash
echo "http://your-server:8000/v1" > secrets/base_url.txt
echo "your-api-key" > secrets/api_key.txt
echo "your-model-name" > secrets/model_name.txt
```

---

## Admin Panel

Web panel at `:3000` for managing the system (protected by Basic Auth):

### Authentication

```bash
# Default credentials
Username: admin
Password: (from secrets/admin_password.txt, default: changeme123)

# Change password
echo "your-secure-password" > secrets/admin_password.txt
docker compose up -d --build admin

# Change username (optional)
# In docker-compose.yml, set environment variable:
# ADMIN_USER=your_username
```

### Pages

| Page | Features |
|------|----------|
| **Dashboard** | Stats, active users, sandboxes |
| **Services** | Start/stop containers |
| **Config** | Agent settings, rate limits |
| **Security** | Blocked patterns management |
| **Tools** | Enable/disable tools |
| **MCP** | Manage MCP servers |
| **Skills** | Install/manage skills |
| **Users** | Sessions, chat history |
| **Logs** | Real-time service logs |

### Remote Access (SSH Tunnel)

Admin panel is bound to `127.0.0.1:3000` for security. For remote access:

```bash
# On your local machine
ssh -L 3000:localhost:3000 user@your-server

# Then open http://localhost:3000 in browser
```

---

## Comparison with Alternatives

| Feature | LocalTopSH | OpenClaw | LangChain |
|---------|------------|----------|-----------|
| **Self-hosted LLM** | ✅ Native | ⚠️ Limited | ✅ Yes |
| **Security hardening** | ✅ 247 patterns | Basic | ❌ None |
| **Sandbox isolation** | ✅ Docker per-user | ✅ Docker | ❌ None |
| **Admin panel** | ✅ React UI | ✅ React UI | ❌ None |
| **Telegram integration** | ✅ Native | ✅ Multi-channel | ❌ None |
| **Setup complexity** | Simple | Complex | Code-only |
| **OAuth/subscription abuse** | ❌ No | ✅ Yes | ❌ No |
| **100% on-premise** | ✅ Yes | ⚠️ Partial | ✅ Yes |

---

## Use Cases

### 🏢 Enterprise

- **Internal AI assistant** with full data privacy
- **Code review bot** that never leaks proprietary code
- **Document analysis** without sending files to cloud

### 🔬 Research

- **Experiment with open models** (Llama, Mistral, Qwen)
- **Fine-tuned model deployment** with agent capabilities
- **Reproducible AI workflows** in isolated environments

### 🌍 Restricted Regions

- **Russia/Belarus/Iran** — no API access restrictions
- **China** — no Great Firewall issues
- **Air-gapped networks** — military, government, finance

### 💰 Cost Optimization

- **High-volume workloads** — pay for GPU, not per-token
- **Predictable costs** — no surprise API bills
- **Scale without limits** — your hardware, your rules

---

## Troubleshooting

### Permission Denied Errors

**Symptom:** `500 Internal Server Error` when changing access mode, or errors like:
```
Permission denied: '/workspace/_shared/admin_config.json'
Permission denied: '/workspace/123456789/'
```

**Cause:** Docker containers (running as `root`) can't write to bind-mounted `workspace/` directory.

**Solution:**
```bash
# Fix permissions on host
chmod -R 777 workspace/

# Or run setup script again
./setup.sh
```

**Prevention:** Always use `./setup.sh` for initial setup — it creates directories with correct permissions.

### Bot Not Responding

**Symptom:** Bot shows online but doesn't reply to messages.

**Diagnosis:**
1. Check if `core` container is running: `docker ps | grep core`
2. Check logs: `docker logs core --tail 50`
3. Verify access mode: Admin panel → Config → Access

**Common causes:**
- Access mode set to `admin_only` but `ADMIN_USER_ID` not configured
- Bot token invalid or expired
- LLM API unreachable (check `base_url` in secrets)

**Solution:**
```bash
# Set admin user ID
echo "YOUR_TELEGRAM_ID" > .env
# Add line: ADMIN_USER_ID=123456789

# Or set access mode to public (for testing)
docker compose restart core
```

### Containers Keep Restarting

**Symptom:** `docker ps` shows containers constantly restarting.

**Diagnosis:**
```bash
docker logs core --tail 100
docker logs bot --tail 100
```

**Common causes:**
- Missing or invalid secrets (telegram_token, api_key, base_url)
- LLM server not accessible
- Port conflicts (3000, 4000, 4001 already in use)

**Solution:**
1. Verify all required secrets exist and are valid
2. Test LLM connection: `curl http://your-llm-server:8000/v1/models`
3. Check port availability: `netstat -tuln | grep -E '3000|4000|4001'`

---

## Philosophy

**We believe in building real infrastructure, not hacks.**

| Approach | LocalTopSH ✅ | Subscription Abuse ❌ |
|----------|--------------|----------------------|
| **LLM Access** | Your own models/keys | Stolen browser sessions |
| **Cost Model** | Pay for hardware | Violate ToS, risk bans |
| **Reliability** | 100% uptime (your infra) | Breaks when UI changes |
| **Security** | Full control | Cookies stored who-knows-where |
| **Ethics** | Transparent & legal | Gray area at best |

---

## License

MIT

---

## Links

- **Architecture**: [ARCHITECTURE.md](ARCHITECTURE.md) — detailed system design
- **Security**: [SECURITY.md](SECURITY.md) — security model and patterns
- **Telegram**: [@neuraldeepchat](https://t.me/neuraldeepchat)
