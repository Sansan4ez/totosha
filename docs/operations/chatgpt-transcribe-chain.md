# ChatGPT Transcribe Chain

Цепочка:

`bot -> proxy /transcribe -> cli-proxy-api /transcribe -> chatgpt backend /backend-api/transcribe`

## Что должно быть готово

- `bot` настроен на `API Type = ChatGPT`
- `ASR URL = http://proxy:3200`
- `proxy` собран с маршрутом `POST /transcribe`
- `cli-proxy-api` собран из патч-ветки `feature/chatgpt-transcribe-endpoint`
- runtime форк берётся из локального checkout `../CLIProxyAPI-fork`
- `cli-proxy-api` стартует с рабочими `config.yaml` и `auths`

## Fork Contract

Текущий ChatGPT-compatible voice path завязан не на generic upstream, а на локальный форк:

- branch contract: `feature/chatgpt-transcribe-endpoint`
- local checkout: `../CLIProxyAPI-fork`
- compatibility route: `POST /transcribe`
- upstream target: `https://chatgpt.com/backend-api/transcribe`

Не заменяйте этот путь generic `/v1/audio/transcriptions`-реализацией при разборе инцидентов. В этой цепочке нужно отличать два разных состояния:

1. Compatibility path works:
   `bot -> proxy -> cli-proxy-api /transcribe -> upstream /backend-api/transcribe` собирается и отвечает корректно.
2. Upstream challenge blocks a working path:
   локальный `/transcribe` маршрут работает, но upstream вместо JSON transcript возвращает HTML challenge.

Во втором случае проблема не в локальном форке маршрута, а в web-session-backed upstream.

## Сборка и запуск

Поднять patched `cli-proxy-api` из локального checkout `../CLIProxyAPI-fork`:

```bash
docker compose -f docker-compose.yml --profile cliproxy up -d --build cli-proxy-api
```

Пересобрать проектный `proxy`:

```bash
docker compose -f docker-compose.yml -f docker-compose.cliproxy.yml up -d --build proxy
```

## Smoke

Проверить каталог моделей:

```bash
curl -sS -i \
  -H 'Authorization: Bearer 57ea5e1d0ea3cf5910c33041d6fa02c1aabcce73cdec7ae37ec64d01606a03ba' \
  http://127.0.0.1:8317/v1/models
```

Ожидание: `200 OK`.

Сгенерировать короткий WAV и проверить `cli-proxy-api` напрямую:

```bash
python3 - <<'PY'
import math, wave, struct
path='/tmp/test-tone.wav'
fr=16000
secs=1
amp=8000
freq=440
with wave.open(path,'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(fr)
    frames=[]
    for i in range(fr*secs):
        sample=int(amp*math.sin(2*math.pi*freq*i/fr))
        frames.append(struct.pack('<h', sample))
    w.writeframes(b''.join(frames))
print(path)
PY

curl -sS -i \
  -H 'Authorization: Bearer 57ea5e1d0ea3cf5910c33041d6fa02c1aabcce73cdec7ae37ec64d01606a03ba' \
  -F 'file=@/tmp/test-tone.wav;type=audio/wav' \
  http://127.0.0.1:8317/transcribe
```

Ожидание: `200 OK` и JSON вида `{"text":"..."}`.

## Operator Diagnostics

Если `POST /transcribe` начинает падать, проверяйте не только smoke, но и per-credential состояние в самом форке:

```bash
curl -sS \
  -H "Authorization: Bearer <CLIPROXY_MGMT_KEY>" \
  http://127.0.0.1:8317/v0/management/transcribe-health

curl -sS \
  -H "Authorization: Bearer <CLIPROXY_MGMT_KEY>" \
  http://127.0.0.1:8317/v0/management/auth-files
```

Ожидания:

- `transcribe-health` показывает `backend_mode=chatgpt_compat`, success/failure/challenge counters и degraded credentials.
- `auth-files` показывает, какой `auth_file` / `auth_index` ловит challenge и ушёл в cooldown.
- Если challenge counters растут, а `POST /transcribe` smoke иногда проходит, это значит: compatibility path жив, но upstream challenge блокирует рабочий путь.

Production recommendation:

- default production ASR должен оставаться `openai` или `faster-whisper`;
- `chatgpt` / `/transcribe` нужно держать как compatibility или fallback-only mode.

Проверить цепочку через проектный `proxy`:

```bash
docker cp /tmp/test-tone.wav bot:/tmp/test-tone.wav
docker exec bot curl -sS -i \
  -F 'file=@/tmp/test-tone.wav;type=audio/wav' \
  http://proxy:3200/transcribe
```

Ожидание: `200 OK` и JSON вида `{"text":"..."}`.

## Откат

1. Остановить patched контейнер:

```bash
docker rm -f cli-proxy-api
```

2. Поднять штатный compose-вариант `cli-proxy-api` из прежнего image/tag.

3. Если нужно, откатить `proxy` на версию без `POST /transcribe` и пересобрать:

```bash
docker compose -f docker-compose.yml -f docker-compose.cliproxy.yml up -d --build proxy
```
