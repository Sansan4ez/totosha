import { createContext, useContext, useState, useEffect } from 'react'
import { getLocale } from './api'

const strings = {
  ru: {
    // Navigation
    'nav.dashboard': '📊 Панель',
    'nav.services': '🐳 Сервисы',
    'nav.config': '⚙️ Настройки',
    'nav.prompt': '📝 Промпт',
    'nav.security': '🛡️ Безопасность',
    'nav.tools': '🔧 Инструменты',
    'nav.mcp': '🔌 MCP',
    'nav.skills': '🎯 Навыки',
    'nav.tasks': '⏰ Задачи',
    'nav.users': '👥 Пользователи',
    'nav.logs': '📜 Логи',

    // Common
    'common.save': '💾 Сохранить',
    'common.reset': '🔄 Сбросить',
    'common.saving': 'Сохранение...',
    'common.loading': 'Загрузка...',
    'common.refresh': '🔄 Обновить',
    'common.delete': 'Удалить',
    'common.enable': 'Включить',
    'common.disable': 'Выключить',
    'common.enabled': 'Включено',
    'common.disabled': 'Отключено',
    'common.status': 'Статус',
    'common.actions': 'Действия',
    'common.name': 'Название',
    'common.error': 'Ошибка',
    'common.success': 'Успешно',
    'common.cancel': 'Отмена',
    'common.confirm': 'Подтвердить',
    'common.search': 'Поиск',
    'common.none': 'Нет',
    'common.yes': 'Да',
    'common.no': 'Нет',

    // Config page
    'config.title': 'Настройки',
    'config.subtitle': 'Настройка параметров системы',
    'config.tab.access': 'Доступ',
    'config.tab.search': 'Поиск',
    'config.tab.asr': 'ASR',
    'config.tab.google': 'Google',
    'config.tab.agent': 'Агент',
    'config.tab.bot': 'Бот',
    'config.tab.userbot': 'Юзербот',
    'config.tab.security': 'Безопасность',
    'config.tab.limits': 'Лимиты',

    // Config - Bot tab
    'config.bot.language': '🌐 Язык / Language',
    'config.bot.language_desc': 'Сообщения бота, тексты ошибок и язык ответов LLM.',
    'config.bot.timezone': '🕐 Часовой пояс',
    'config.bot.timezone_current': 'Текущее время',
    'config.bot.timezone_restart': '⚠️ После сохранения перезапустите контейнеры.',
    'config.bot.reactions': 'Реакции',
    'config.bot.thoughts': 'Случайные мысли',
    'config.bot.reaction_chance': 'Шанс реакции',
    'config.bot.random_reply': 'Шанс случайного ответа',

    // Config - Agent tab
    'config.agent.model': 'Модель',
    'config.agent.temperature': 'Температура',
    'config.agent.max_iterations': 'Макс. итераций',
    'config.agent.tool_timeout': 'Таймаут инструментов',

    // Config - Search tab
    'config.search.title': '🔍 Веб-поиск (ZAI)',
    'config.search.desc': 'Настройка поиска в интернете через Z.AI API.',
    'config.search.mode': 'Режим поиска',
    'config.search.model': 'Модель поиска',
    'config.search.response_model': 'Модель ответа (после поиска)',
    'config.search.response_model_desc_on': 'После search_web финальный ответ сгенерирует',
    'config.search.response_model_desc_off': 'Отключено — основная модель генерирует все ответы (может отвечать на английском)',
    'config.search.results_count': 'Количество результатов',
    'config.search.recency': 'Фильтр по дате',
    'config.search.timeout': 'Таймаут (секунды)',
    'config.search.save': '💾 Сохранить настройки поиска',

    // Config - ASR tab
    'config.asr.title': '🎤 Распознавание речи (ASR)',
    'config.asr.desc': 'Транскрипция голосовых через Whisper API (OpenAI-compatible, ChatGPT или Faster-Whisper).',
    'config.asr.online': '✅ ASR Онлайн',
    'config.asr.offline': '❌ ASR Офлайн',
    'config.asr.disabled_status': '⏸️ ASR Отключён',
    'config.asr.enable': 'Включить голосовые',
    'config.asr.url': 'URL сервера ASR',
    'config.asr.url_desc': 'Базовый URL Whisper сервера или полный endpoint транскрибации (/transcribe или /v1/audio/transcriptions).',
    'config.asr.language': 'Язык',
    'config.asr.max_duration': 'Макс. длительность (секунды)',
    'config.asr.timeout': 'Таймаут (секунды)',
    'config.asr.save': '💾 Сохранить ASR',

    // Config - Security tab
    'config.security.prompt_filter': 'Фильтр промпт-инъекций',
    'config.security.block_patterns': 'Блокировка опасных паттернов',
    'config.security.sandbox': 'Изоляция в песочнице',
    'config.security.max_blocked': 'Макс. заблокированных команд до блокировки',

    // Config - Limits tab
    'config.limits.sandbox_ttl': 'TTL песочницы (минуты)',
    'config.limits.sandbox_memory': 'Лимит памяти песочницы',
    'config.limits.max_tool_output': 'Макс. вывод инструмента (символы)',
    'config.limits.max_context': 'Макс. сообщений контекста',

    // Config - Access tab
    'config.access.mode': 'Режим доступа',
    'config.access.admin_id': 'ID администратора',
    'config.access.bot_enabled': 'Бот включён',
    'config.access.userbot_enabled': 'Юзербот включён',
    'config.access.allowlist': 'Белый список',
    'config.access.add_user': 'Добавить пользователя',

    // Dashboard
    'dashboard.title': 'Панель управления',
    'dashboard.subtitle': 'Мониторинг системы',
    'dashboard.uptime': 'Аптайм',
    'dashboard.memory': 'Память',
    'dashboard.cpu': '💻 CPU',
    'dashboard.model': 'Модель',
    'dashboard.sessions': 'Сессии',
    'dashboard.tools': 'Инструменты',
    'dashboard.memory_label': '🧠 Память',
    'dashboard.disk': '💾 Диск',
    'dashboard.network': '🌐 Сеть',
    'dashboard.active_users': 'Активные пользователи',
    'dashboard.active_sandboxes': 'Активные песочницы',
    'dashboard.requests_today': 'Запросов сегодня',
    'dashboard.tools_executed': 'Инструментов выполнено',
    'dashboard.services_table': 'Сервисы',
    'dashboard.col_service': 'Сервис',
    'dashboard.col_status': 'Статус',
    'dashboard.col_uptime': 'Аптайм',
    'dashboard.col_memory': 'Память',
    'dashboard.recent_requests': 'Последние запросы',
    'dashboard.no_activity': 'Нет активности',
    'dashboard.security_events': 'События безопасности',
    'dashboard.no_security': '✓ Нет событий безопасности',

    // Services
    'services.title': 'Сервисы',
    'services.subtitle': 'Управление Docker-контейнерами',
    'services.restart': '🔄 Перезапустить',
    'services.stop': '⏹️ Остановить',
    'services.start': '▶️ Запустить',
    'services.healthy': 'Работает',
    'services.unhealthy': 'Ошибка',
    'services.stopped': 'Остановлен',
    'services.image': 'Образ',
    'services.uptime': 'Аптайм',
    'services.memory_label': 'Память',
    'services.cpu': 'CPU',
    'services.ports': 'Порты',
    'services.load': 'Загрузить',

    // Tools
    'tools.title': 'Инструменты',
    'tools.subtitle': 'Управление инструментами агента',

    // Users
    'users.title': 'Пользователи',
    'users.subtitle': 'Активные пользователи и сессии',

    // Logs
    'logs.title': 'Логи',
    'logs.subtitle': 'Логи сервисов в реальном времени',

    // Prompt
    'prompt.title': 'Системный промпт',
    'prompt.subtitle': 'Редактирование системного промпта агента',
    'prompt.save': '💾 Сохранить промпт',
    'prompt.restore': '↩️ Восстановить из бэкапа',

    // Security
    'security.title': 'Безопасность',
    'security.subtitle': 'Паттерны безопасности и фильтры',

    // MCP
    'mcp.title': 'MCP Серверы',
    'mcp.subtitle': 'Model Context Protocol серверы',

    // Skills
    'skills.title': 'Навыки',
    'skills.subtitle': 'Управление навыками агента',

    // Tasks
    'tasks.title': 'Задачи',
    'tasks.subtitle': 'Запланированные задачи и напоминания',

    // Logs details
    'logs.service': 'Сервис',
    'logs.lines': 'Строк',
    'logs.auto_refresh': 'Авто-обновление',
    'logs.refresh': '🔄 Обновить',
    'logs.logs_of': 'логи',
    'logs.lines_count': 'строк',
    'logs.no_logs': 'Нет логов',

    // Security details
    'security.add_pattern': 'Добавить паттерн',
    'security.add_btn': '➕ Добавить',
    'security.blocked_patterns': 'Заблокированные паттерны',
    'security.filter': 'Фильтр...',
    'security.no_patterns': 'Паттерны не найдены',

    // Tools details
    'tools.no_description': 'Нет описания',
    'tools.used_times': 'Использовано {count} раз',
    'tools.no_tools': 'Нет доступных инструментов',

    // Users details
    'users.sandboxes_tab': '🐳 Песочницы',
    'users.sessions_tab': '💬 Сессии',
    'users.no_sandboxes': 'Нет активных песочниц',
    'users.no_sessions': 'Нет сессий',
    'users.col_user_id': 'ID пользователя',
    'users.col_container': 'Контейнер',
    'users.col_ports': 'Порты',
    'users.col_active': 'Активен',
    'users.col_actions': 'Действия',
    'users.col_messages': 'Сообщения',
    'users.col_last_active': 'Последняя активность',
    'users.kill': '⏹️ Убить',
    'users.close': '✕ Закрыть',
    'users.user_label': 'Пользователь',
    'users.user_msg': 'Пользователь:',
    'users.assistant_msg': 'Ассистент:',
    'users.no_messages': 'Нет сообщений',
    'users.memory_label': 'Память',

    // MCP details
    'mcp.refresh_all': '🔄 Обновить все',
    'mcp.refreshing': '⏳ Обновление...',
    'mcp.add_server': '➕ Добавить сервер',
    'mcp.no_servers': 'Нет настроенных MCP серверов',
    'mcp.no_servers_hint': 'Добавьте сервер для загрузки внешних инструментов',
    'mcp.tools_count': '{count} инструментов',
    'mcp.available_tools': 'Доступные инструменты:',
    'mcp.more': '+{count} ещё',
    'mcp.modal_title': 'Добавить MCP сервер',
    'mcp.name': 'Название *',
    'mcp.url': 'URL *',
    'mcp.api_key': 'Bearer токен (необязательно)',
    'mcp.api_key_placeholder': 'Оставьте пустым, если не нужен',
    'mcp.description': 'Описание',
    'mcp.cancel': 'Отмена',
    'mcp.disabled': 'отключён',

    // Skills details
    'skills.scan': '🔍 Сканировать',
    'skills.scanning': '⏳ Сканирование...',
    'skills.install_skill': '📦 Установить навык',
    'skills.installed_tab': 'Установлено',
    'skills.available_tab': 'Доступно',
    'skills.no_skills': 'Нет установленных навыков',
    'skills.no_skills_hint': 'Установите навыки из вкладки Доступно или создайте свои',
    'skills.all_installed': 'Все доступные навыки установлены',
    'skills.no_description': 'Нет описания',
    'skills.commands': 'Команды:',
    'skills.install_btn': '📥 Установить',
    'skills.installed_badge': '✅ Установлено',
    'skills.modal_title': 'Установить навык',
    'skills.anthropic_official': 'Anthropic Skills (Официальные)',
    'skills.close': 'Закрыть',

    // Tasks details
    'tasks.active_tasks': 'Активные задачи',
    'tasks.refresh': 'Обновить',
    'tasks.no_tasks': 'Нет запланированных задач. Агент может создавать задачи инструментом schedule_task.',
    'tasks.col_id': 'ID',
    'tasks.col_user': 'Пользователь',
    'tasks.col_type': 'Тип',
    'tasks.col_content': 'Содержание',
    'tasks.col_next_run': 'Следующий запуск',
    'tasks.col_time_left': 'Осталось',
    'tasks.col_recurring': 'Повтор',
    'tasks.col_source': 'Источник',
    'tasks.col_actions': 'Действия',
    'tasks.recurring_every': '🔄 каждые {min}м',
    'tasks.once': 'однократно',
    'tasks.cancel': 'Отменить',
    'tasks.task_types': '📖 Типы задач',
    'tasks.type_message': 'Отправить напоминание пользователю',
    'tasks.type_agent': 'Запустить агента с промптом (может использовать инструменты, поиск и т.д.)',

    // Prompt details
    'prompt.saving': '💾 Сохранение...',
    'prompt.save_btn': '💾 Сохранить',
    'prompt.unsaved': '⚠️ Есть несохранённые изменения',
    'prompt.placeholder': 'Содержимое системного промпта...',
    'prompt.help_title': 'Доступные плейсхолдеры:',
    'prompt.help_tools': 'Список доступных инструментов (название + описание)',
    'prompt.help_skills': 'Установленные навыки с описаниями',
    'prompt.help_cwd': 'Рабочая директория пользователя',
    'prompt.help_date': 'Текущая дата/время',
    'prompt.help_ports': 'Назначенные порты для серверов пользователя',
    'prompt.help_tip': '💡 Изменения применяются сразу — перезапуск не нужен!',
    'prompt.loading': 'Загрузка промпта...',
    'prompt.restore_confirm': 'Восстановить из бэкапа?',

    // Config - Access tab details
    'config.access.title': '🔐 Управление доступом',
    'config.access.desc': 'Запуск/остановка сервисов. При остановке контейнер полностью выключается.',
    'config.access.admin_title': '👑 Администратор',
    'config.access.admin_label': 'ID админа:',
    'config.access.not_set': 'Не задан',
    'config.access.configure_warning': '⚠️ Укажите ID админа!',
    'config.access.edit': '✏️ Изменить',
    'config.access.save': '✓ Сохранить',
    'config.access.admin_hint': 'Узнайте свой Telegram ID у @userinfobot',
    'config.access.mode_title': '🎯 Режим доступа',
    'config.access.mode_admin': '👑 Только админ',
    'config.access.mode_allowlist': '📋 Белый список',
    'config.access.mode_public': '🌍 Публичный',
    'config.access.mode_admin_desc': '🔒 Только админ ({id}) может использовать бота',
    'config.access.mode_allowlist_desc': '📋 Админ + пользователи из белого списка',
    'config.access.mode_public_desc': '⚠️ Все могут использовать бота',
    'config.access.allowlist_title': '📋 Белый список',
    'config.access.add_user_placeholder': 'Telegram User ID',
    'config.access.add_user_btn': '➕ Добавить',
    'config.access.no_users': 'Нет пользователей в белом списке',
    'config.access.remove': 'Удалить',
    'config.access.services_title': '🐳 Сервисы',
    'config.access.bot_label': 'Telegram Бот',
    'config.access.userbot_label': 'Юзербот',

    // Toast messages
    'toast.sandbox_killed': 'Песочница уничтожена',
    'toast.session_cleared': 'Сессия очищена',
    'toast.task_cancelled': 'Задача отменена',
    'toast.pattern_added': 'Паттерн добавлен',
    'toast.pattern_deleted': 'Паттерн удалён',
    'toast.config_saved': 'Конфигурация сохранена!',
    'toast.asr_saved': 'Конфигурация ASR сохранена!',
    'toast.search_saved': 'Конфигурация поиска сохранена!',
    'toast.prompt_saved': 'Промпт сохранён! Перезапустите core для применения.',
    'toast.prompt_restored': 'Восстановлено из бэкапа!',
    'toast.failed_load': 'Не удалось загрузить: {msg}',
    'toast.failed_save': 'Не удалось сохранить: {msg}',
    'toast.failed_restore': 'Не удалось восстановить: {msg}',
    'toast.failed_session': 'Не удалось загрузить детали сессии',
    'toast.invalid_admin_id': 'Введите корректный Telegram User ID',
    'toast.invalid_user_id': 'Введите корректный User ID',
    'toast.name_url_required': 'Название и URL обязательны',
    'toast.server_added': 'Сервер "{name}" добавлен',
    'toast.server_removed': 'Сервер "{name}" удалён',
    'toast.server_toggled': 'Сервер "{name}" {state}',
    'toast.server_refreshed': 'Загружено {count} инструментов из "{name}"',
    'toast.servers_refreshed': 'Обновлено {servers} серверов, {tools} инструментов',
    'toast.skill_toggled': 'Навык "{name}" {state}',
    'toast.skill_scanned': 'Найдено {count} навыков',
    'toast.skill_installed': 'Навык "{name}" установлен',
    'toast.skill_uninstalled': 'Навык "{name}" удалён',
    'toast.tool_toggled': 'Инструмент {state}',
    'toast.enabled': 'включён',
    'toast.disabled': 'отключён',
    'toast.failed_cancel': 'Не удалось отменить',
    'toast.loading_services': 'Загрузка сервисов...',
    'toast.mode_set': 'Режим установлен: {mode}',
    'toast.admin_id_set': 'ID админа установлен: {id}',
    'toast.user_added': 'Пользователь {id} добавлен',
    'toast.user_removed': 'Пользователь {id} удалён',

    // Config misc
    'config.access.personal_account': 'Личный аккаунт',

    // MCP tooltips
    'mcp.disable_server': 'Отключить сервер',
    'mcp.enable_server': 'Включить сервер',

    // Config search mode descriptions
    'config.search.mode_coding_desc': 'Chat Completions + tools (api/coding/paas/v4) — быстрее, включает AI-суммаризацию',
    'config.search.mode_basic_desc': 'Отдельный web_search endpoint (api/paas/v4) — базовый, возможны строгие лимиты',

    // Confirm dialogs
    'confirm.kill_sandbox': 'Уничтожить песочницу пользователя {id}?',
    'confirm.clear_session': 'Очистить сессию пользователя {id}?',
    'confirm.cancel_task': 'Отменить задачу {id}?',
    'confirm.uninstall_skill': 'Удалить навык "{name}"?',
    'confirm.delete_pattern': 'Удалить паттерн: {pattern}?',
    'confirm.remove_server': 'Удалить MCP сервер "{name}"?',
    'confirm.restore_backup': 'Восстановить из бэкапа?',

    // Misc
    'misc.not_deployed': 'не развёрнут',
    'misc.unknown': 'неизвестно',
    'misc.lines': 'строк',
    'misc.chars': 'символов',

    // Footer
    'footer.version': 'AI Agent Framework v1.0',
  },
  en: {
    // Navigation
    'nav.dashboard': '📊 Dashboard',
    'nav.services': '🐳 Services',
    'nav.config': '⚙️ Config',
    'nav.prompt': '📝 Prompt',
    'nav.security': '🛡️ Security',
    'nav.tools': '🔧 Tools',
    'nav.mcp': '🔌 MCP',
    'nav.skills': '🎯 Skills',
    'nav.tasks': '⏰ Tasks',
    'nav.users': '👥 Users',
    'nav.logs': '📜 Logs',

    // Common
    'common.save': '💾 Save',
    'common.reset': '🔄 Reset',
    'common.saving': 'Saving...',
    'common.loading': 'Loading...',
    'common.refresh': '🔄 Refresh',
    'common.delete': 'Delete',
    'common.enable': 'Enable',
    'common.disable': 'Disable',
    'common.enabled': 'Enabled',
    'common.disabled': 'Disabled',
    'common.status': 'Status',
    'common.actions': 'Actions',
    'common.name': 'Name',
    'common.error': 'Error',
    'common.success': 'Success',
    'common.cancel': 'Cancel',
    'common.confirm': 'Confirm',
    'common.search': 'Search',
    'common.none': 'None',
    'common.yes': 'Yes',
    'common.no': 'No',

    // Config page
    'config.title': 'Configuration',
    'config.subtitle': 'Adjust system settings',
    'config.tab.access': 'Access',
    'config.tab.search': 'Search',
    'config.tab.asr': 'ASR',
    'config.tab.google': 'Google',
    'config.tab.agent': 'Agent',
    'config.tab.bot': 'Bot',
    'config.tab.userbot': 'Userbot',
    'config.tab.security': 'Security',
    'config.tab.limits': 'Limits',

    // Config - Bot tab
    'config.bot.language': '🌐 Language',
    'config.bot.language_desc': 'Bot messages, error texts, and LLM language enforcement.',
    'config.bot.timezone': '🕐 Timezone',
    'config.bot.timezone_current': 'Current time',
    'config.bot.timezone_restart': '⚠️ After saving, restart containers for changes to take effect.',
    'config.bot.reactions': 'Reactions',
    'config.bot.thoughts': 'Random Thoughts',
    'config.bot.reaction_chance': 'Reaction Chance',
    'config.bot.random_reply': 'Random Reply Chance',

    // Config - Agent tab
    'config.agent.model': 'Model',
    'config.agent.temperature': 'Temperature',
    'config.agent.max_iterations': 'Max Iterations',
    'config.agent.tool_timeout': 'Tool Timeout',

    // Config - Search tab
    'config.search.title': '🔍 Web Search (ZAI)',
    'config.search.desc': 'Configure how the bot searches the web via Z.AI API.',
    'config.search.mode': 'Search Mode',
    'config.search.model': 'Search Model',
    'config.search.response_model': 'Response Model (after search)',
    'config.search.response_model_desc_on': 'After search_web, final answer will be generated by',
    'config.search.response_model_desc_off': 'Disabled — main model generates all responses (may answer in English)',
    'config.search.results_count': 'Results Count',
    'config.search.recency': 'Recency Filter',
    'config.search.timeout': 'Timeout (seconds)',
    'config.search.save': '💾 Save Search Config',

    // Config - ASR tab
    'config.asr.title': '🎤 Speech-to-Text (ASR)',
    'config.asr.desc': 'Voice message transcription via Whisper API (OpenAI-compatible, ChatGPT, or Faster-Whisper).',
    'config.asr.online': '✅ ASR Online',
    'config.asr.offline': '❌ ASR Offline',
    'config.asr.disabled_status': '⏸️ ASR Disabled',
    'config.asr.enable': 'Enable Voice Messages',
    'config.asr.url': 'ASR Server URL',
    'config.asr.url_desc': 'Base Whisper server URL or full transcription endpoint (/transcribe or /v1/audio/transcriptions).',
    'config.asr.language': 'Language',
    'config.asr.max_duration': 'Max Voice Duration (seconds)',
    'config.asr.timeout': 'Timeout (seconds)',
    'config.asr.save': '💾 Save ASR Config',

    // Config - Security tab
    'config.security.prompt_filter': 'Prompt Injection Filter',
    'config.security.block_patterns': 'Block Sensitive Patterns',
    'config.security.sandbox': 'Sandbox Isolation',
    'config.security.max_blocked': 'Max Blocked Commands Before Lock',

    // Config - Limits tab
    'config.limits.sandbox_ttl': 'Sandbox TTL (minutes)',
    'config.limits.sandbox_memory': 'Sandbox Memory Limit',
    'config.limits.max_tool_output': 'Max Tool Output (chars)',
    'config.limits.max_context': 'Max Context Messages',

    // Config - Access tab
    'config.access.mode': 'Access Mode',
    'config.access.admin_id': 'Admin User ID',
    'config.access.bot_enabled': 'Bot Enabled',
    'config.access.userbot_enabled': 'Userbot Enabled',
    'config.access.allowlist': 'Allowlist',
    'config.access.add_user': 'Add User',

    // Dashboard
    'dashboard.title': 'Dashboard',
    'dashboard.subtitle': 'System monitoring',
    'dashboard.uptime': 'Uptime',
    'dashboard.memory': 'Memory',
    'dashboard.cpu': '💻 CPU',
    'dashboard.model': 'Model',
    'dashboard.sessions': 'Sessions',
    'dashboard.tools': 'Tools',
    'dashboard.memory_label': '🧠 Memory',
    'dashboard.disk': '💾 Disk',
    'dashboard.network': '🌐 Network',
    'dashboard.active_users': 'Active Users',
    'dashboard.active_sandboxes': 'Active Sandboxes',
    'dashboard.requests_today': 'Requests Today',
    'dashboard.tools_executed': 'Tools Executed',
    'dashboard.services_table': 'Services',
    'dashboard.col_service': 'Service',
    'dashboard.col_status': 'Status',
    'dashboard.col_uptime': 'Uptime',
    'dashboard.col_memory': 'Memory',
    'dashboard.recent_requests': 'Recent Requests',
    'dashboard.no_activity': 'No recent activity',
    'dashboard.security_events': 'Security Events',
    'dashboard.no_security': '✓ No security events',

    // Services
    'services.title': 'Services',
    'services.subtitle': 'Docker container management',
    'services.restart': '🔄 Restart',
    'services.stop': '⏹️ Stop',
    'services.start': '▶️ Start',
    'services.healthy': 'Healthy',
    'services.unhealthy': 'Unhealthy',
    'services.stopped': 'Stopped',
    'services.image': 'Image',
    'services.uptime': 'Uptime',
    'services.memory_label': 'Memory',
    'services.cpu': 'CPU',
    'services.ports': 'Ports',
    'services.load': 'Load',

    // Tools
    'tools.title': 'Tools',
    'tools.subtitle': 'Manage agent tools',

    // Users
    'users.title': 'Users',
    'users.subtitle': 'Active users and sessions',

    // Logs
    'logs.title': 'Logs',
    'logs.subtitle': 'Real-time service logs',

    // Prompt
    'prompt.title': 'System Prompt',
    'prompt.subtitle': 'Edit agent system prompt',
    'prompt.save': '💾 Save Prompt',
    'prompt.restore': '↩️ Restore from Backup',

    // Security
    'security.title': 'Security',
    'security.subtitle': 'Security patterns and filters',

    // MCP
    'mcp.title': 'MCP Servers',
    'mcp.subtitle': 'Model Context Protocol servers',

    // Skills
    'skills.title': 'Skills',
    'skills.subtitle': 'Manage agent skills',

    // Tasks
    'tasks.title': 'Tasks',
    'tasks.subtitle': 'Scheduled tasks and reminders',

    // Logs details
    'logs.service': 'Service',
    'logs.lines': 'Lines',
    'logs.auto_refresh': 'Auto-refresh',
    'logs.refresh': '🔄 Refresh',
    'logs.logs_of': 'logs',
    'logs.lines_count': 'lines',
    'logs.no_logs': 'No logs available',

    // Security details
    'security.add_pattern': 'Add New Pattern',
    'security.add_btn': '➕ Add',
    'security.blocked_patterns': 'Blocked Patterns',
    'security.filter': 'Filter...',
    'security.no_patterns': 'No patterns found',

    // Tools details
    'tools.no_description': 'No description',
    'tools.used_times': 'Used {count} times',
    'tools.no_tools': 'No tools available',

    // Users details
    'users.sandboxes_tab': '🐳 Sandboxes',
    'users.sessions_tab': '💬 Sessions',
    'users.no_sandboxes': 'No active sandboxes',
    'users.no_sessions': 'No sessions found',
    'users.col_user_id': 'User ID',
    'users.col_container': 'Container',
    'users.col_ports': 'Ports',
    'users.col_active': 'Active',
    'users.col_actions': 'Actions',
    'users.col_messages': 'Messages',
    'users.col_last_active': 'Last Active',
    'users.kill': '⏹️ Kill',
    'users.close': '✕ Close',
    'users.user_label': 'User',
    'users.user_msg': 'User:',
    'users.assistant_msg': 'Assistant:',
    'users.no_messages': 'No messages',
    'users.memory_label': 'Memory',

    // MCP details
    'mcp.refresh_all': '🔄 Refresh All',
    'mcp.refreshing': '⏳ Refreshing...',
    'mcp.add_server': '➕ Add Server',
    'mcp.no_servers': 'No MCP servers configured',
    'mcp.no_servers_hint': 'Add a server to load external tools',
    'mcp.tools_count': '{count} tools',
    'mcp.available_tools': 'Available tools:',
    'mcp.more': '+{count} more',
    'mcp.modal_title': 'Add MCP Server',
    'mcp.name': 'Name *',
    'mcp.url': 'URL *',
    'mcp.api_key': 'Bearer token (optional)',
    'mcp.api_key_placeholder': 'Leave empty if not needed',
    'mcp.description': 'Description',
    'mcp.cancel': 'Cancel',
    'mcp.disabled': 'disabled',

    // Skills details
    'skills.scan': '🔍 Scan Skills',
    'skills.scanning': '⏳ Scanning...',
    'skills.install_skill': '📦 Install Skill',
    'skills.installed_tab': 'Installed',
    'skills.available_tab': 'Available',
    'skills.no_skills': 'No skills installed',
    'skills.no_skills_hint': 'Install skills from the Available tab or create custom ones',
    'skills.all_installed': 'All available skills are installed',
    'skills.no_description': 'No description',
    'skills.commands': 'Commands:',
    'skills.install_btn': '📥 Install',
    'skills.installed_badge': '✅ Installed',
    'skills.modal_title': 'Install Skill',
    'skills.anthropic_official': 'Anthropic Skills (Official)',
    'skills.close': 'Close',

    // Tasks details
    'tasks.active_tasks': 'Active Tasks',
    'tasks.refresh': 'Refresh',
    'tasks.no_tasks': 'No scheduled tasks. Agent can create tasks using the schedule_task tool.',
    'tasks.col_id': 'ID',
    'tasks.col_user': 'User',
    'tasks.col_type': 'Type',
    'tasks.col_content': 'Content',
    'tasks.col_next_run': 'Next Run',
    'tasks.col_time_left': 'Time Left',
    'tasks.col_recurring': 'Recurring',
    'tasks.col_source': 'Source',
    'tasks.col_actions': 'Actions',
    'tasks.recurring_every': '🔄 every {min}m',
    'tasks.once': 'once',
    'tasks.cancel': 'Cancel',
    'tasks.task_types': '📖 Task Types',
    'tasks.type_message': 'Send a reminder message to the user',
    'tasks.type_agent': 'Run the agent with a prompt (can use tools, search, etc.)',

    // Prompt details
    'prompt.saving': '💾 Saving...',
    'prompt.save_btn': '💾 Save',
    'prompt.unsaved': '⚠️ You have unsaved changes',
    'prompt.placeholder': 'System prompt content...',
    'prompt.help_title': 'Available placeholders:',
    'prompt.help_tools': 'List of available tools (name + description)',
    'prompt.help_skills': 'Installed skills with descriptions',
    'prompt.help_cwd': "User's working directory",
    'prompt.help_date': 'Current date/time',
    'prompt.help_ports': "Assigned ports for user's servers",
    'prompt.help_tip': '💡 Changes apply immediately - no restart needed!',
    'prompt.loading': 'Loading prompt...',
    'prompt.restore_confirm': 'Restore from backup?',

    // Config - Access tab details
    'config.access.title': '🔐 Access Control',
    'config.access.desc': 'Start/stop services. When stopped, the container is completely down.',
    'config.access.admin_title': '👑 Admin User',
    'config.access.admin_label': 'Admin ID:',
    'config.access.not_set': 'Not set',
    'config.access.configure_warning': '⚠️ Configure admin ID!',
    'config.access.edit': '✏️ Edit',
    'config.access.save': '✓ Save',
    'config.access.admin_hint': 'Get your Telegram ID from @userinfobot',
    'config.access.mode_title': '🎯 Access Mode',
    'config.access.mode_admin': '👑 Admin Only',
    'config.access.mode_allowlist': '📋 Allowlist',
    'config.access.mode_public': '🌍 Public',
    'config.access.mode_admin_desc': '🔒 Only admin ({id}) can use the bot',
    'config.access.mode_allowlist_desc': '📋 Admin + users in allowlist can use the bot',
    'config.access.mode_public_desc': '⚠️ Everyone can use the bot',
    'config.access.allowlist_title': '📋 Allowlist',
    'config.access.add_user_placeholder': 'Telegram User ID',
    'config.access.add_user_btn': '➕ Add',
    'config.access.no_users': 'No users in allowlist',
    'config.access.remove': 'Remove',
    'config.access.services_title': '🐳 Services',
    'config.access.bot_label': 'Telegram Bot',
    'config.access.userbot_label': 'Userbot',

    // Toast messages
    'toast.sandbox_killed': 'Sandbox killed',
    'toast.session_cleared': 'Session cleared',
    'toast.task_cancelled': 'Task cancelled',
    'toast.pattern_added': 'Pattern added',
    'toast.pattern_deleted': 'Pattern deleted',
    'toast.config_saved': 'Configuration saved!',
    'toast.asr_saved': 'ASR config saved!',
    'toast.search_saved': 'Search config saved!',
    'toast.prompt_saved': 'Prompt saved! Restart core to apply changes.',
    'toast.prompt_restored': 'Restored from backup!',
    'toast.failed_load': 'Failed to load: {msg}',
    'toast.failed_save': 'Failed to save: {msg}',
    'toast.failed_restore': 'Failed to restore: {msg}',
    'toast.failed_session': 'Failed to load session details',
    'toast.invalid_admin_id': 'Enter valid Telegram user ID',
    'toast.invalid_user_id': 'Enter valid user ID',
    'toast.name_url_required': 'Name and URL are required',
    'toast.server_added': 'Server "{name}" added',
    'toast.server_removed': 'Server "{name}" removed',
    'toast.server_toggled': 'Server "{name}" {state}',
    'toast.server_refreshed': 'Loaded {count} tools from "{name}"',
    'toast.servers_refreshed': 'Refreshed {servers} servers, {tools} tools',
    'toast.skill_toggled': 'Skill "{name}" {state}',
    'toast.skill_scanned': 'Found {count} skills',
    'toast.skill_installed': 'Skill "{name}" installed',
    'toast.skill_uninstalled': 'Skill "{name}" uninstalled',
    'toast.tool_toggled': 'Tool {state}',
    'toast.enabled': 'enabled',
    'toast.disabled': 'disabled',
    'toast.failed_cancel': 'Failed to cancel',
    'toast.loading_services': 'Loading services...',
    'toast.mode_set': 'Mode set to: {mode}',
    'toast.admin_id_set': 'Admin ID set to: {id}',
    'toast.user_added': 'User {id} added',
    'toast.user_removed': 'User {id} removed',

    // Config misc
    'config.access.personal_account': 'Personal account',

    // MCP tooltips
    'mcp.disable_server': 'Disable server',
    'mcp.enable_server': 'Enable server',

    // Config search mode descriptions
    'config.search.mode_coding_desc': 'Chat Completions + tools (api/coding/paas/v4) — faster, includes AI summary',
    'config.search.mode_basic_desc': 'Separate web_search endpoint (api/paas/v4) — basic, may have stricter rate limits',

    // Confirm dialogs
    'confirm.kill_sandbox': 'Kill sandbox for user {id}?',
    'confirm.clear_session': 'Clear session for user {id}?',
    'confirm.cancel_task': 'Cancel task {id}?',
    'confirm.uninstall_skill': 'Uninstall skill "{name}"?',
    'confirm.delete_pattern': 'Delete pattern: {pattern}?',
    'confirm.remove_server': 'Remove MCP server "{name}"?',
    'confirm.restore_backup': 'Restore from backup?',

    // Misc
    'misc.not_deployed': 'not deployed',
    'misc.unknown': 'unknown',
    'misc.lines': 'lines',
    'misc.chars': 'chars',

    // Footer
    'footer.version': 'AI Agent Framework v1.0',
  },
}

const I18nContext = createContext({ t: (k) => k, lang: 'en' })

export function I18nProvider({ children }) {
  const [lang, setLang] = useState('en')

  useEffect(() => {
    getLocale()
      .then(data => setLang(data.language || 'en'))
      .catch(() => {})
  }, [])

  // Listen for locale changes (re-fetch every 30s or on visibility)
  useEffect(() => {
    const refresh = () => {
      getLocale()
        .then(data => setLang(data.language || 'en'))
        .catch(() => {})
    }
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) refresh()
    })
  }, [])

  function t(key, params) {
    const s = strings[lang] || strings['en']
    let text = s[key] || strings['en'][key] || key
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        text = text.replace(`{${k}}`, v)
      })
    }
    return text
  }

  return (
    <I18nContext.Provider value={{ t, lang, setLang }}>
      {children}
    </I18nContext.Provider>
  )
}

export function useT() {
  return useContext(I18nContext)
}

export default I18nContext
