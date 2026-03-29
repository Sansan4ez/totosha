# ChatGPT Transcribe Chain

Цепочка:

`bot -> proxy /transcribe -> cli-proxy-api /transcribe -> chatgpt backend /backend-api/transcribe`

## Что должно быть готово

- `bot` настроен на `API Type = ChatGPT`
- `ASR URL = http://proxy:3200`
- `proxy` собран с маршрутом `POST /transcribe`
- `cli-proxy-api` собран из патч-ветки `feature/chatgpt-transcribe-endpoint`
- `cli-proxy-api` стартует с рабочими `config.yaml` и `auths`

## Сборка и запуск

Поднять patched `cli-proxy-api` из локального checkout `../CLIProxyAPI`:

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
