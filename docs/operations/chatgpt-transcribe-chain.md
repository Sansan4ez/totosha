# ChatGPT Transcribe Chain (retired)

**Статус: retired as of 2026-07-13.** Проект переключён с `../CLIProxyAPI-fork`
(ветка `feature/chatgpt-transcribe-endpoint`) на чистый upstream
`../CLIProxyAPI`. Chистый upstream не содержит маршрута `POST /transcribe`,
поэтому ChatGPT-compatible voice path, описанный ниже, больше не работает.

## Что это значило раньше

Цепочка `bot -> proxy /transcribe -> cli-proxy-api /transcribe -> chatgpt
backend /backend-api/transcribe` зависела от кастомного патча в форке
(`internal/api/handlers/openai/openai_transcribe_handler.go` и смежные
файлы, ~1500 строк). Этот патч не был смёржен в upstream
`router-for-me/CLIProxyAPI`, поэтому его больше нет в рантайме.

## Текущее состояние

- `cli-proxy-api` собирается из `../CLIProxyAPI` (chистый upstream, main).
- `POST /transcribe` и `/v0/management/transcribe-health` endpoints
  отсутствуют.
- `config.yaml` и `auths/*` перенесены из `../CLIProxyAPI-fork` без изменений
  (см. `docker-compose.yml`), так что Codex/Claude/Gemini OAuth-проксирование
  продолжает работать как прежде — сломан только `chatgpt`-ASR compat path.
- В `core/admin_api.py` (`_test_asr_connection`) остался код, который
  сообщает `status: ready` для `api_type == "chatgpt"` без реальной проверки
  — это устаревшая информация, требует отдельного ревью, если voice ASR на
  `chatgpt`-backend всё ещё используется где-то в конфигурации.

## Рекомендация

- Production ASR должен использовать `openai`-compatible или
  `faster-whisper` backend (см. RFC-023) — они не зависят от кастомного
  форка.
- Если ChatGPT-compat voice path снова понадобится, патч из
  `feature/chatgpt-transcribe-endpoint` (коммиты `61c39b43`, `8345446d`,
  `e6a22216` в `/home/admin/CLIProxyAPI-fork`) можно re-apply поверх
  текущего `../CLIProxyAPI` через cherry-pick/rebase.

## Откат на форк (если нужно восстановить старое поведение)

```bash
# в docker-compose.yml вернуть build/volumes на ../CLIProxyAPI-fork
docker compose -f docker-compose.yml --profile cliproxy up -d --build cli-proxy-api
```

`../CLIProxyAPI-fork` не удалён и остаётся рабочим checkout'ом со своим
`config.yaml`/`auths` (которые были только скопированы, не перемещены, в
`../CLIProxyAPI`).
