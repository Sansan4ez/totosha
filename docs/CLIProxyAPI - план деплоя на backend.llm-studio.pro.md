# CLIProxyAPI — деплой на backend.llm-studio.pro (89.124.65.212) **в составе проекта `totosha` (один docker-compose.yml)**

Цель:
- поднять **CLIProxyAPI** рядом с `totosha` на одном VPS
- **полностью заменить текущий upstream** LLM в `totosha` на CLIProxyAPI через:
  - `secrets/base_url.txt`
  - `secrets/api_key.txt`
- использовать CLIProxyAPI **локально**:
  - запросы к `/v1/*` идут только из контейнеров `totosha` (внутри docker network)
  - web-админка CLIProxyAPI доступна только:
    - на сервере (loopback),
    - либо с ноутбука через SSH tunnel

Основа: tutorial-5 (Docker Server Deployment)
https://help.router-for.me/hands-on/tutorial-5.html

Ключевое отличие от tutorial-5:
- **не публикуем лишние порты** (1455/54545/…)
- для Codex логина предпочитаем **device flow** (`--codex-device-login`)

---

## 0) Предпосылки
- Ubuntu 24.04
- вход по SSH как `admin`
- Docker установлен
- `docker compose` работает
- проект `totosha` запускается через `totosha/docker-compose.yml`

---

## 1) Модель секретов: 2 разных ключа (обязательно)

CLIProxyAPI имеет *два* независимых уровня доступа:

1) **Client API key** — ключ для доступа к `/v1/*` (именно его будет использовать `totosha/proxy`).
   - хранится в CLIProxyAPI в `api-keys:`
   - передаётся клиентом как `Authorization: Bearer <key>`

2) **Management key** — ключ для `/v0/management/*` и web-админки.
   - хранится в `remote-management.secret-key` (или `MANAGEMENT_PASSWORD`)

⚠️ **Не используйте один и тот же ключ** для обоих.

Генерация:

```bash
openssl rand -hex 32  # CLIPROXY_CLIENT_KEY
openssl rand -hex 32  # CLIPROXY_MGMT_KEY
```

---

## 2) Где хранить конфиг и OAuth-токены на хосте

Не кладите токены в `totosha/workspace/_shared`: этот каталог монтируется во многие сервисы (`/data`).
Чтобы не раздавать OAuth-токены лишним контейнерам, держим данные CLIProxyAPI отдельно:

- `/opt/cliproxyapi/`
  - `config.yaml` (с ключами)
  - `auths/` (OAuth токены/аккаунты)
  - `static/` (кэш management.html)
  - `logs/` (если когда-нибудь включите file-logging)

Создание:

```bash
sudo mkdir -p /opt/cliproxyapi/{auths,static,logs}
sudo chown -R root:root /opt/cliproxyapi
sudo chmod 755 /opt/cliproxyapi
sudo chmod 700 /opt/cliproxyapi/auths
sudo chmod 755 /opt/cliproxyapi/static /opt/cliproxyapi/logs
```

---

## 3) Конфиг CLIProxyAPI: `/opt/cliproxyapi/config.yaml`

Минимум для безопасной локальной работы:
- `api-keys` **обязательно** (иначе API может оказаться “открытым” внутри сети)
- management key **обязательно** (иначе админка не включится)
- `request-log: false` + `commercial-mode: true`
  - важно: иначе CLIProxyAPI может писать тела запросов/ответов в логи хотя бы “на ошибках”

Пример (заполните ключи):

```yaml
host: "0.0.0.0"
port: 8317

# В Docker оставляем дефолт (как в tutorial-5): токены под /root/.cli-proxy-api
auth-dir: "~/.cli-proxy-api"

# Ключи доступа к /v1/* (их будет использовать totosha/proxy)
api-keys:
  - "9d9e458cb27beaae37723b48ad86b995da620e3a82062f98c2fabd5ac157e880"

remote-management:
  # Важно: при доступе к web UI через проброс 127.0.0.1:8317
  # запросы приходят не как localhost (из docker bridge), поэтому ставим true.
  allow-remote: true

  # plaintext допустим — при старте он будет захеширован (bcrypt)
  secret-key: "0fcfb9d5db3ec2b099044688215f210559d2961d2f214c19a2b84c2c3f5a9cd6"

  disable-control-panel: false

pprof:
  enable: false

debug: false
usage-statistics-enabled: false

request-log: false
commercial-mode: true

logging-to-file: false
logs-max-total-size-mb: 0
error-logs-max-files: 10
```


```
sudo bash -lc 'set -euo pipefail

CLIENT="$(cat /opt/cliproxyapi/client_key.txt)"
MGMT="$(cat /opt/cliproxyapi/mgmt_key.txt)"

cat > /opt/cliproxyapi/config.yaml <<EOF
host: "0.0.0.0"
port: 8317

auth-dir: "~/.cli-proxy-api"

api-keys:
 - "${CLIENT}"

remote-management:
 allow-remote: true
 secret-key: "${MGMT}"
 disable-control-panel: false

pprof:
 enable: false

debug: false
usage-statistics-enabled: false

request-log: false
commercial-mode: true

logging-to-file: false
logs-max-total-size-mb: 0
error-logs-max-files: 10
EOF

chmod 600 /opt/cliproxyapi/config.yaml
'
```
---

## 4) Изменения в `totosha/docker-compose.yml` (уже внесены локально)

В вашем репозитории `totosha` я добавил:
- сервис `cli-proxy-api` (профиль `cliproxy`)
- сеть `cliproxy-net`
- подключил `proxy` к `cliproxy-net`

Смысл сети: только `proxy` и `cli-proxy-api` могут общаться напрямую.

Если будете переносить изменения на сервер вручную — проверьте, что в `docker-compose.yml` есть:
- `services.cli-proxy-api`
- `networks.cliproxy-net`
- у `proxy` в `networks`: `agent-net` и `cliproxy-net`

---

## 5) Запуск CLIProxyAPI (в составе totosha)

CLIProxyAPI помечен профилем `cliproxy`.

Из директории, где лежит `totosha/docker-compose.yml`:

```
cd /opt/totosha

sudo docker compose -f /opt/totosha/docker-compose.yml exec -T proxy python -c \
"import urllib.request; print(urllib.request.urlopen('http://localhost:3200/health',timeout=10).read()[:200])"

sudo docker compose -f /opt/totosha/docker-compose.yml exec -T proxy python -c \
"import urllib.request; print(urllib.request.urlopen('http://localhost:3200/v1/models',timeout=30).read()[:400])"
```

```bash
sudo docker compose --profile cliproxy pull cli-proxy-api
sudo docker compose --profile cliproxy up -d cli-proxy-api
sudo docker compose ps
```

Проверка на сервере:

```bash
curl -sS http://127.0.0.1:8317/ | head
```

---

## 6) Доступ к web-админке CLIProxyAPI через SSH tunnel

На локальном компьютере:

```bash
ssh -L 8317:127.0.0.1:8317 admin@backend.llm-studio.pro
```

Открыть:
- http://localhost:8317/management.html

Для management API/UI нужен ключ `remote-management.secret-key`.

Пример вызова management API:

```bash
curl -H "Authorization: Bearer <CLIPROXY_MGMT_KEY>" http://localhost:8317/v0/management/config
```

---

## 7) OAuth для Codex на сервере

### Рекомендую: device flow (без callback-портов)

На сервере:

```bash
sudo docker compose --profile cliproxy exec cli-proxy-api \
  /CLIProxyAPI/CLIProxyAPI -no-browser --codex-device-login
```

CLIProxyAPI выведет URL и код. Откройте URL на ноутбуке, введите код → токены сохранятся в `/opt/cliproxyapi/auths`.

### Альтернатива (как в tutorial-5): callback flow через SSH tunnel
Этот способ потребует временно публиковать callback-порт (например 1455) на `127.0.0.1` хоста.
С вашим current threat model device flow проще и безопаснее.

---

## 8) Полная замена upstream в `totosha` на CLIProxyAPI

`totosha` ходит в LLM через контейнер `proxy`, а `proxy` читает:
- `secrets/base_url.txt`
- `secrets/api_key.txt`

Чтобы заменить upstream:

### 8.1 Обновить secrets

**`totosha/secrets/base_url.txt`**

```text
http://cli-proxy-api:8317/v1
```

**`totosha/secrets/api_key.txt`**

```text
<CLIPROXY_CLIENT_KEY>
```

Права:

```bash
chmod 600 secrets/base_url.txt secrets/api_key.txt
```

### 8.2 Перезапустить `proxy` (и при необходимости core)

```bash
sudo docker compose up -d --force-recreate proxy

# если хотите гарантированно обновить цепочку, можно и core:
# sudo docker compose up -d --force-recreate proxy core
```

---

## 9) Model name: что поставить в `secrets/model_name.txt`

После перехода на CLIProxyAPI некоторые старые значения (например openrouter-идентификаторы) могут быть недоступны.

Правильный порядок:
1) Сначала выполните OAuth login (например Codex device flow).
2) Посмотрите доступные модели:

```bash
curl -sS \
  -H "Authorization: Bearer <CLIPROXY_CLIENT_KEY>" \
  http://127.0.0.1:8317/v1/models | head
```

3) Поставьте `secrets/model_name.txt` в один из доступных model id.

---

## 10) Чек-лист безопасности
- [ ] Порт 8317 опубликован только как `127.0.0.1:8317:8317` (не `0.0.0.0:8317`)
- [ ] `CLIPROXY_CLIENT_KEY` и `CLIPROXY_MGMT_KEY` разные
- [ ] В `config.yaml` задан `api-keys` (иначе /v1/* может стать “без auth”)
- [ ] `request-log: false` и `commercial-mode: true`
- [ ] `/opt/cliproxyapi/auths` имеет права `700` и не монтируется в другие контейнеры

---

## 11) Что осталось уточнить
1) Нужен ли вам Codex только для части запросов, или всё в CLIProxyAPI (Gemini/Claude тоже)?
2) Хотите ли вы собирать CLIProxyAPI из pinned tag/commit (безопаснее и воспроизводимее), или достаточно `latest`?
