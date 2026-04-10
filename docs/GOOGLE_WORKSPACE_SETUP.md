# Google Workspace MCP - Настройка

Интеграция Gmail, Calendar, Drive, Docs, Sheets и других сервисов Google.

## Быстрый старт

### 1. Создание OAuth приложения в Google Cloud Console

1. Перейдите в [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте новый проект или выберите существующий
3. Включите необходимые API:
   - Gmail API
   - Google Calendar API
   - Google Drive API
   - Google Docs API
   - Google Sheets API

### 2. Настройка OAuth 2.0 Credentials

1. Перейдите в **APIs & Services → Credentials**
2. Нажмите **Create Credentials → OAuth client ID**
3. Тип приложения: **Desktop app** (рекомендуется) или **Web application**
4. Для Web application добавьте redirect URI:
   ```
   http://localhost:8500/oauth2callback
   ```
5. Сохраните **Client ID** и **Client Secret**

### 3. Добавление credentials в LocalTopSH

```bash
# Записать Client ID
echo "YOUR_CLIENT_ID.apps.googleusercontent.com" > secrets/gdrive_client_id.txt

# Записать Client Secret  
echo "YOUR_CLIENT_SECRET" > secrets/gdrive_client_secret.txt
```

### 4. Перезапуск сервисов

```bash
docker compose up -d google-workspace-mcp
docker compose restart core
```

## OAuth авторизация

При первом использовании Gmail/Calendar/Drive инструментов:

1. Агент вернёт URL для авторизации
2. Откройте URL в браузере
3. Войдите в Google аккаунт и разрешите доступ
4. Google перенаправит на callback URL
5. Токены сохранятся автоматически

### Пример использования через Telegram бота:

```
Пользователь: Покажи мои последние 5 писем
Агент: Для доступа к Gmail требуется авторизация. 
       Перейдите по ссылке: https://accounts.google.com/...
       
[После авторизации]
Агент: Ваши последние письма:
       1. От: boss@company.com - "Срочно: отчёт"
       2. От: github.com - "New PR review request"
       ...
```

## Доступные инструменты (44 шт)

### Gmail
- `gmail_search` - поиск писем
- `gmail_read` - чтение письма
- `gmail_send` - отправка писем
- `gmail_reply` - ответ на письмо
- `gmail_trash` - удаление в корзину
- `gmail_label` - управление метками

### Calendar
- `calendar_list` - список календарей
- `calendar_events` - события
- `calendar_create_event` - создание события
- `calendar_update_event` - обновление
- `calendar_delete_event` - удаление

### Drive
- `drive_list` - список файлов
- `drive_search` - поиск файлов
- `drive_read` - чтение файла
- `drive_create` - создание файла
- `drive_upload` - загрузка файла

### Docs / Sheets / Slides
- `docs_read` / `docs_create` / `docs_update`
- `sheets_read` / `sheets_create` / `sheets_update`
- `slides_read` / `slides_create`

### Tasks
- `tasks_list` - список задач
- `tasks_create` - создание задачи
- `tasks_complete` - отметить выполненной

### Contacts
- `contacts_search` - поиск контактов
- `contacts_create` - создание контакта

## Настройка периодических задач

Для автоматического мониторинга почты используйте scheduler:

```
Пользователь: Каждый день в 9:00 присылай сводку новых писем
Агент: Задача создана. Буду присылать сводку ежедневно в 9:00.
```

## Переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `GOOGLE_MCP_PORT` | Порт для OAuth callback | `8500` |
| `GOOGLE_WORKSPACE_EXTERNAL_URL` | Внешний URL (за прокси) | `http://localhost:8500` |
| `TOOL_TIER` | Набор инструментов: `core`, `extended`, `complete` | `core` |

## Устранение неполадок

### "OAuth client ID not configured"
- Проверьте что файлы `secrets/gdrive_client_id.txt` и `secrets/gdrive_client_secret.txt` существуют
- Перезапустите контейнер: `docker compose restart google-workspace-mcp`

### "Invalid redirect URI"
- В Google Cloud Console добавьте redirect URI: `http://localhost:8500/oauth2callback`
- Для внешнего доступа используйте `GOOGLE_WORKSPACE_EXTERNAL_URL`

### Токен истёк
- Токены обновляются автоматически
- При проблемах удалите credentials volume проекта, например: `docker volume rm totosha_google-workspace-creds`

## Безопасность

- OAuth токены хранятся в Docker volume `google-workspace-creds` (в compose-проекте `totosha` это обычно `totosha_google-workspace-creds`)
- Токены шифруются
- Доступ только к разрешённым scope
- Рекомендуется использовать отдельный Google аккаунт для тестирования

## Ссылки

- [Google Workspace MCP](https://github.com/taylorwilsdon/google_workspace_mcp) - исходный код
- [Google Cloud Console](https://console.cloud.google.com/) - управление API
- [Gmail API Docs](https://developers.google.com/gmail/api) - документация Gmail API
