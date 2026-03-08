# Первоначальная настройка VPS (Ubuntu 24.04): безопасность + Docker Compose + Caddy + GitHub CI/CD

Руководство для приложений: **Telegram Bot (aiogram)** и **FastAPI**.

Цель: базовая “боеспособная” настройка сервера по принципу **least privilege**.

> Важно: на новом VPS обычно сначала заходят как `root` (или как дефолтный юзер провайдера).
> **Root-аккаунт оставляем**, но **SSH-вход под root отключаем** после того, как проверим вход под обычным админом.

---

## 0) База: обновления и утилиты

```bash
sudo apt update
sudo apt -y upgrade

# полезное (можно расширять)
sudo apt -y install ca-certificates curl gnupg git ufw fail2ban ripgrep
```

---

## 1) Пользователи: admin для обслуживания + deployer для CI/CD

Почему так:
- **root** нужен системе, но **ему не нужен прямой SSH-доступ** (это самая частая цель атак).
- **admin**: человек, который руками обслуживает сервер (имеет sudo).
- **deployer**: ключ из GitHub Actions, который умеет только деплоить (без полного sudo).

### 1.1 Создать admin (с паролем)

`admin` — ваш ручной админ. Пароль полезен:
- для `sudo` (по умолчанию sudo спрашивает пароль пользователя)
- как аварийный доступ через консоль провайдера

```bash
sudo adduser admin
sudo usermod -aG sudo admin
```

### 1.2 Создать deployer (без пароля и без группы sudo)

`deployer` используется GitHub Actions для деплоя. Пароль не нужен, если:
- SSH только по ключу
- ключ ограничен `command="..."` и `no-pty`
- `sudo` настроен как `NOPASSWD` на один деплой-скрипт

```bash
sudo adduser --disabled-password --gecos "" deployer
# НЕ добавляем deployer в sudo
```

Если пользователь уже создан и хотите запретить вход по паролю (заблокировать пароль):

```bash
sudo passwd -l deployer
```

> Важно: даже если у пользователя есть пароль, при настройках SSH
> `PasswordAuthentication no` и `KbdInteractiveAuthentication no`
> по SSH пароль всё равно не примется. Пароль останется только для локальной консоли / sudo (если не `NOPASSWD`).

### 1.3 Добавить SSH-ключи (правильно, без копирования root-прав)

На сервере создаём `.ssh` и `authorized_keys` с корректными владельцами/правами.

**Для admin:**

```bash
sudo install -d -m 700 -o admin -g admin /home/admin/.ssh
sudo touch /home/admin/.ssh/authorized_keys
sudo chown admin:admin /home/admin/.ssh/authorized_keys
sudo chmod 600 /home/admin/.ssh/authorized_keys

# Вариант A (рекомендуется): скопировать ключ с хоста одной командой
# ssh-copy-id -i ~/.ssh/id_ed25519.pub admin@<server-ip>

# Вариант B: вручную вставьте публичный ключ (id_ed25519.pub) в файл
sudo -u admin nano /home/admin/.ssh/authorized_keys
```

**Для deployer (для GitHub Actions):**

```bash
sudo install -d -m 700 -o deployer -g deployer /home/deployer/.ssh
sudo touch /home/deployer/.ssh/authorized_keys
sudo chown deployer:deployer /home/deployer/.ssh/authorized_keys
sudo chmod 600 /home/deployer/.ssh/authorized_keys

sudo -u deployer nano /home/deployer/.ssh/authorized_keys
```

### 1.4 Проверка (не закрывайте текущую root-сессию)

В **новом** терминале проверьте:

```bash
ssh admin@<server-ip>
```

Только после этого переходите к отключению root-логина.

Проверка в каких группах 'deployer':
```bash
id deployer
groups deployer
```
---

## 2) SSH hardening (Ubuntu 24.04): `sshd_config.d/` + `systemctl reload ssh`

В Ubuntu 24.04 удобно не править основной файл `/etc/ssh/sshd_config`, а класть свои настройки в:

- `/etc/ssh/sshd_config.d/*.conf`

Создаём файл, например:

```bash
sudo nano /etc/ssh/sshd_config.d/99-hardening.conf
```

Рекомендуемый минимум:

```conf
# запретить SSH-вход под root
PermitRootLogin no

# отключить парольный вход
PasswordAuthentication no
KbdInteractiveAuthentication no

# включить вход по ключам
PubkeyAuthentication yes
AuthenticationMethods publickey

# разрешить вход только этим пользователям
AllowUsers admin deployer

# мелочи, которые обычно не нужны на VPS
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
```

Применяем безопасно:

```bash
# 1) проверяем синтаксис (если ошибка — НЕ перезагружаем)
sudo sshd -t

# 2) применяем без разрыва текущих соединений
sudo systemctl reload ssh

# 3) проверяем статус
sudo systemctl status ssh --no-pager
```

Опционально (после того, как точно есть доступ через `admin`):

```bash
# блокируем пароль root (root всё равно доступен через sudo)
sudo passwd -l root
```

---

## 3) Firewall (UFW)

Открываем только нужное: SSH + HTTP/HTTPS для Caddy.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH: лучше limit (rate-limit) вместо allow
sudo ufw limit OpenSSH

# Caddy (сертификаты Let's Encrypt требуют 80/tcp, и обычно нужен 443/tcp)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

sudo ufw enable
sudo ufw status verbose
```

---

## 4) Fail2ban для SSH (минимальный конфиг)

Fail2ban — не “анти-DDoS”, а защита от брутфорса (в первую очередь SSH).

```bash
sudo systemctl enable --now fail2ban
```

Создайте jail:

```bash
sudo nano /etc/fail2ban/jail.d/sshd.local
```

Минимум:

```ini
[sshd]
enabled = true
port = ssh
maxretry = 5
findtime = 10m
bantime = 1h
banaction = ufw
```

Применить:

```bash
sudo systemctl restart fail2ban
sudo fail2ban-client status sshd
```

---

## 5) Установка Docker Engine + Docker Compose (plugin)

На Ubuntu 24.04 рекомендуется ставить Docker из официального репозитория Docker.

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo systemctl enable --now docker

docker version
docker compose version
```

### Важное про права

- Добавление пользователя в группу `docker` даёт ему **почти root-доступ** (через доступ к Docker socket).
- Для least-privilege лучше: **Docker управляет только root/admin**, а `deployer` вызывает строго разрешённый deploy-скрипт через sudo (см. ниже).

---

## 6) Структура каталогов под Compose и секреты

Рекомендуемый каталог проекта на сервере:

- `/opt/totosha/` — compose, Caddyfile
- `/opt/totosha/secrets/` — env-файлы (root-only)

```bash
sudo mkdir -p /opt/totosha/secrets
sudo chown -R root:root /opt/totosha
sudo chmod 755 /opt/totosha
sudo chmod 700 /opt/totosha/secrets
```

Примеры secret env-файлов:

```bash
sudo nano /opt/totosha/secrets/tgbot.env
sudo nano /opt/totosha/secrets/fastapi.env

sudo chmod 600 /opt/totosha/secrets/*.env
```

---

## 7) Caddy как reverse proxy (вместо nginx)

Caddy проще для VPS: сам получает/обновляет TLS-сертификаты (Let’s Encrypt).

Создайте файл:

```bash
sudo nano /opt/totosha/Caddyfile
```

Пример (проксируем FastAPI из контейнера):

```caddy
your-domain.com {
	encode zstd gzip
	reverse_proxy fastapi:8000
}
```

Требования:
- DNS A-запись `your-domain.com` должна указывать на IP сервера
- порты **80** и **443** должны быть доступны снаружи (см. UFW)

---

## 8) Docker Compose: сервисы в контейнерах

Создайте `compose.yaml`:

```bash
sudo nano /opt/totosha/compose.yaml
```

Шаблон (образы предполагаются из registry, например GHCR):

```yaml
name: totosha

services:
  fastapi:
    image: ghcr.io/ORG/fastapi:latest
    env_file:
      - ./secrets/fastapi.env
    expose:
      - "8000"
    restart: unless-stopped
    networks: [internal]

  tgbot:
    image: ghcr.io/ORG/tgbot:latest
    env_file:
      - ./secrets/tgbot.env
    restart: unless-stopped
    networks: [internal]

  caddy:
    image: caddy:2
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    restart: unless-stopped
    networks: [internal]

volumes:
  caddy_data:
  caddy_config:

networks:
  internal:
    driver: bridge
```

Запуск:

```bash
cd /opt/totosha
sudo docker compose pull
sudo docker compose up -d

sudo docker compose ps
sudo docker compose logs -f --tail 200
```

---

## 9) GitHub CI/CD деплой (без выдачи deployer полного sudo)

Идея:
1) GitHub Actions **собирает образы**, пушит в registry (например GHCR)
2) Actions по SSH вызывает на сервере **одну фиксированную команду деплоя**
3) На сервере деплой делает root через заранее подготовленный скрипт

### 9.1 Deploy-скрипт на сервере

Создайте файл:

```bash
sudo nano /usr/local/bin/deploy-totosha
sudo chmod 755 /usr/local/bin/deploy-totosha
sudo chown root:root /usr/local/bin/deploy-totosha
```

Содержимое:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /opt/totosha

# Обновить образы и применить
/usr/bin/docker compose pull
/usr/bin/docker compose up -d --remove-orphans

# (опционально) почистить старые образы
/usr/bin/docker image prune -f
```

### 9.2 Разрешаем deployer запускать ТОЛЬКО этот скрипт через sudo без пароля

```bash
sudo visudo -f /etc/sudoers.d/deployer-deploy
```

Вставьте:

```sudoers
deployer ALL=(root) NOPASSWD: /usr/local/bin/deploy-totosha
```

Проверка:

```bash
sudo -u deployer sudo -n /usr/local/bin/deploy-totosha
```

### 9.3 (Опционально, но рекомендуется) “зажать” SSH-ключ deployer до одной команды

В `/home/deployer/.ssh/authorized_keys` можно добавить ограничения.
Пример строки (в одну строку):

```text
command="sudo -n /usr/local/bin/deploy-totosha",no-port-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... github-actions
```

Так этот ключ **не сможет открыть shell**, а только запустит деплой.

---

## 10. Run CLIproxyAPI with Docker Compose

1. Clone the repository and navigate into the directory:
    
    ```
    git clone https://github.com/router-for-me/CLIProxyAPI.git
    cd CLIProxyAPI
    ```
    
2. Prepare the configuration file: Create a `config.yaml` file by copying the example and customize it to your needs.
    
    ```
    cp config.example.yaml config.yaml
    ```
    
    _(Note for Windows users: You can use `copy config.example.yaml config.yaml` in CMD or PowerShell.)_
    
3. Start the service:
    
    - **For most users (recommended):** Run the following command to start the service using the pre-built image from Docker Hub. The service will run in the background.
        
        ```
        docker compose up -d
        ```

---
## Разъяснения:
1. admin sudo требует пароль. Это нормально, но автоматом (без TTY) sudo не выполнится. Дальнейшие изменения делайте руками из SSH-сессии admin.
	 Это идеально для ручного администрирования. Просто важно понимать ограничение: если вы попытаетесь использовать admin в автоматизации (скрипт/CI), то sudo упрётся в запрос
	 пароля (или в отсутствие TTY). Поэтому:
	 - руками — используем admin;
	 - автоматом — используем deployer + NOPASSWD на один скрипт.
2. deployer пока не готов для CI (нет ключа) — ему надо добавить ключ в /home/deployer/.ssh/authorized_keys (с правами 700/600). Сейчас вход как deployer у вас, вероятно, не настроен (по крайней мере моим ключом он не пускал).
	deployer пока не готов для CI (нет ключа)
	 Сейчас пользователь deployer создан, но вход по SSH для него не работает (по крайней мере тем ключом, которым я проверял). Для CI это означает: GitHub Actions не сможет подключиться, пока вы:
	 - сгенерите отдельный ключ для CI,
	 - добавите публичный ключ в /home/deployer/.ssh/authorized_keys,
	 - проверите права 700/600.
3. Для запуска Caddy позже: убедитесь, что DNS A-запись backend.llm-studio.pro указывает на 89.124.65.212, иначе TLS не выпишется.


## 10) Чек-лист после настройки

- [ ] Есть рабочий вход по SSH под `admin` по ключу
- [ ] `PermitRootLogin no`, парольный вход отключён
- [ ] UFW включён, открыты только 22/80/443
- [ ] Fail2ban активен для `sshd`
- [ ] Docker и `docker compose` установлены
- [ ] `compose.yaml`, `Caddyfile`, `secrets/*.env` лежат в `/opt/totosha`
- [ ] `deployer` не в группе `sudo` и не в группе `docker`
- [ ] Деплой делается через `sudo /usr/local/bin/deploy-totosha`
