# Установка и предварительная подготовка VPS для LocalTopSH

Сценарий: один VPS для всего стека (LLM backend + LocalTopSH), доступ к админке только через SSH tunnel, `userbot` и Google Workspace MCP включены сразу.

## 1. Требования к VPS

- ОС: Ubuntu 22.04/24.04 LTS
- Ресурсы: минимум `4 vCPU / 8 GB RAM / 40+ GB disk`
- Сеть:
  - Открыт только SSH (`22/tcp`)
  - Порты `3000`, `3200`, `4000`, `4001`, `8100` не должны быть доступны извне

## 2. Базовая подготовка сервера

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install git curl ca-certificates ufw docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker

docker --version
docker compose version
```

## 3. Настройка firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw limit OpenSSH
sudo ufw enable
sudo ufw status
```

Важно: не открывайте наружу внутренние порты стека (`3000/3200/4000/4001/8100`).

## 4. Клонирование и bootstrap проекта

```bash
git clone https://github.com/Sansan4ez/topsha.git
cd topsha
./setup.sh
```

Скрипт создаст `secrets/`, `workspace/`, `workspace/_shared` и базовые файлы секретов.

## 5. Заполнить обязательные секреты

Обязательно заполнить:

- `secrets/telegram_token.txt`
- `secrets/base_url.txt`
- `secrets/api_key.txt`
- `secrets/model_name.txt`
- `secrets/admin_password.txt` (сменить дефолт)

Рекомендуемо/опционально:

- `secrets/zai_api_key.txt` (web search)

Для `userbot` (раз включаем сразу):

- `secrets/telegram_api_id.txt`
- `secrets/telegram_api_hash.txt`
- `secrets/telegram_phone.txt`

Пример для single-VPS с локальным LLM API:

```bash
echo "http://127.0.0.1:8000/v1" > secrets/base_url.txt
echo "dummy" > secrets/api_key.txt
echo "gpt-oss-120b" > secrets/model_name.txt
```

## 6. Настроить `.env`

Создать из шаблона:

```bash
cp .env.example .env
```

Минимально проверить и задать:

- `ADMIN_USER_ID=<ваш telegram user id>`
- `ACCESS_MODE=admin`
- `ADMIN_PORT=3000`
- `TZ=UTC` (или ваш timezone)

## 7. Закрыть админку на localhost

В `docker-compose.yml` для сервиса `admin` использовать localhost binding:

```yaml
ports:
  - "127.0.0.1:${ADMIN_PORT:-3000}:3000"
```

Это исключает прямой внешний доступ к админке.

## 8. Запуск (с userbot профилем)

```bash
docker compose --profile userbot up -d --build
```

## 9. Проверка после деплоя

```bash
docker compose ps
python3 scripts/doctor.py
docker logs corp-db-migrator --tail 100

docker logs core --tail 100
docker logs bot --tail 100
docker logs userbot --tail 100
docker logs google-workspace-mcp --tail 100
```

Если `doctor.py` показывает критические проблемы — исправить до боевого запуска.
Для существующих `corp-db` volume `corp-db-migrator` автоматически применяет live-upgrade RFC-026; если он упал или `doctor.py` показывает drift, выполнить `docker compose up -d --build corp-db corp-db-migrator tools-api` и перепроверить.

## 10. Доступ к админке через SSH tunnel

На локальной машине:

```bash
ssh -L 3000:localhost:3000 user@your-vps
```

После этого открыть в браузере:

- `http://localhost:3000`

## 11. Post-deploy рекомендации

- Не переключать `ACCESS_MODE` в `public` без необходимости
- Не публиковать `proxy/core/bot` порты наружу
- Делать бэкап `secrets/` и `workspace/_shared/`
- После каждого security-патча прогонять `python3 scripts/doctor.py`

##  12. Adding Skill
1. Create directory in `/workspace/_shared/skills/{name}/`
2. Add `skill.json` with metadata
3. Add `SKILL.md` with full instructions
4. Skill will be auto-discovered on next agent run
