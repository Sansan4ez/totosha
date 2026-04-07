---
name: corp-pg-db
description: Поиск по корпоративной базе Postgres: company facts, контакты, реквизиты, сайт, адрес, соцсети, сервис, гарантия, светильники, коды/артикулы, категории, сферы, портфолио, типы крепления и promoted subset базы знаний. Используй вместе с tool `corp_db_search`. Не используй shell или прямой SQL для доступа к этой базе.
---

# Corp PG DB

Используй этот skill, когда вопрос связан со структурированными корпоративными данными:
- company facts: год основания, сайт, адрес, соцсети, контакты, реквизиты, сервис, гарантия, общая информация о компании;
- конкретный светильник или серия;
- ETM/ORACL код, артикул, коробочное наименование;
- категория, сфера применения, объект из портфолио;
- тип крепления или совместимость креплений;
- подбор кандидатов по параметрам (`IP65`, `5000K`, `25Вт`, температура, напряжение);
- promoted subset базы знаний, который уже индексируется в Postgres.

## Основное правило

- Используй только tool `corp_db_search`.
- Не используй `run_command`, SQL CLI и прямое чтение файлов как способ обратиться к корпоративной БД.
- Для коротких company-fact вопросов `corp_db_search` является default-path.
- Если после поиска в БД нужен свободный текстовый контекст, правило или цитата из документа, дополнительно используй `doc-search`.

## Режимы поиска

- `kind=hybrid_search`
  - `profile=entity_resolver` для неточного поиска по названию, коду, категории, объекту, креплению
  - `profile=candidate_generation` для подбора по описанию задачи и признакам
  - `profile=kb_search` для promoted KB subset в БД, включая company facts и индексированные company documents
  - `profile=related_evidence` для добора обоснования после резолва сущности
- `kind=lamp_exact` для точного совпадения по названию лампы
- `kind=portfolio_examples_by_lamp` для цепочки `точная модель -> категория -> сфера -> объекты портфолио`
- `kind=application_recommendation` для broad-object подбора по сфере применения: `стадион`, `карьер`, `аэропорт`, `склад`, `офис`, `высокие пролёты`, `агрессивная среда`
- `kind=sku_by_code` для ETM/ORACL
- `kind=lamp_filters` для фильтрации по параметрам
- `kind=category_lamps`, `portfolio_by_sphere`, `sphere_categories`, `category_mountings` для связанных выборок

## Правило для точной модели

- Если в вопросе уже есть точное или почти точное имя модели светильника, сначала выбери правильный exact path по смыслу вопроса.
- Типичные признаки exact-model запроса:
  - полное имя вроде `LAD LED R500-9-30-6-650LZD`
  - короткий код той же модели вроде `R500-9-30-6-650LZD`
  - точное коробочное название без описательных слов
- Если вопрос про `примеры реализации`, `объекты`, `портфолио`, `где применялся`, `какие проекты были`, сначала используй `kind=portfolio_examples_by_lamp`.
- Если `portfolio_examples_by_lamp` вернул `success`, считай модель и объекты подтверждёнными и отвечай по этому payload.
- После успешного `portfolio_examples_by_lamp` не делай `hybrid_search`, `sphere_categories`, `portfolio_by_sphere`, wiki-поиск или shell-поиск, если пользователь не просил дополнительно свободный текстовый контекст.
- Если `portfolio_examples_by_lamp` дал `empty`, честно скажи, что по найденной модели объекты портфолио не найдены; переходи к wiki только по явному запросу на расширенный контекст.
- Если пользователь просит `портфолио`, `пример проекта`, `пример объекта`, но НЕ называет точную модель, сначала используй `kind=portfolio_by_sphere`.
- Для таких запросов передавай короткую сферу/объект в `sphere` и ставь `fuzzy=true`.
- После успешного `portfolio_by_sphere` не делай `application_recommendation`, `hybrid_search` или `doc-search` для того же ответа, если пользователь не просил свободный текстовый контекст.
- Для остальных exact-model вопросов используй `kind=lamp_exact`.
- Если `lamp_exact` вернул `success`, считай модель найденной и отвечай по этому payload.
- Не делай после успешного `lamp_exact` дополнительный `hybrid_search`, `lamp_suggest` или wiki-поиск, если пользователь не просил:
  - похожие модели
  - альтернативы
  - документы
  - свободный текстовый контекст
- Только если `lamp_exact` дал `empty`, переходи к `hybrid_search`, `lamp_suggest` или `sku_by_code`.

## Правило для broad-object подбора по сфере применения

- Если пользователь просит подобрать светильник или освещение для объекта/сцены применения, а не называет точную модель:
  - `стадион`, `арена`, `спорткомплекс`
  - `карьер`, `рудник`, `ГОК`
  - `аэропорт`, `апрон`, `перрон`
  - `склад`, `высокие пролёты`
  - `офис`, `кабинет`, `АБК`
  - `агрессивная среда`, `мойка`, `АЗС`
- Сначала используй `kind=application_recommendation`.
- Передавай в `query` исходную формулировку пользователя.
- Если в запросе есть явные признаки, передавай их и в structured args: `power_w_*`, `ip`, `mounting_type`, `explosion_protected`, `beam_pattern`, `weight_kg_*`, `voltage_*`, `dimensions_raw`.
- Если `application_recommendation` вернул `success`, отвечай по его payload и останавливайся.
- Первый ответ по этому payload должен содержать:
  - распознанную сферу применения;
  - 2–3 подходящие модели/серии;
  - ссылки на карточки и, когда есть, изображения;
  - 1–2 примера портфолио;
  - один уточняющий вопрос из `follow_up_question`.
- После успешного `application_recommendation` не делай `hybrid_search`, `category_lamps`, `sphere_categories`, `portfolio_by_sphere`, `doc-search` или shell-поиск для того же ответа.
- Если `application_recommendation` дал `needs_clarification`, задай только уточняющий вопрос из payload и не подставляй случайные модели.
- Только если `application_recommendation` дал `empty`, переходи к `hybrid_search profile=candidate_generation` или проси уточнить сферу/параметры.

## Правило для company facts

- Если вопрос про сайт, адрес, соцсети, контакты, реквизиты, сервис, гарантию, год основания, консультацию или общую информацию о компании, сначала используй `kind=hybrid_search` с `profile=kb_search`.
- Когда это уместно, передавай `entity_types=["company"]`.
- Если `corp_db_search(kind=hybrid_search, profile=kb_search)` вернул `success` для короткого company-fact вопроса, отвечай по этому payload и останавливайся.
- После успешного company-fact `kb_search` не делай `doc-search`, `doc_search`, `corp-wiki-md-search`, `corp_wiki_search`, `run_command`, `list_directory`, `read_file` или `search_text`, если пользователь явно не просил wiki/document context.
- Только если company-fact `kb_search` дал `empty` или ошибку, переключайся на `doc-search`.
- Если вопрос по смыслу документный: `сертификат`, `PDF`, `паспорт`, `закалённое стекло`, `чем отличается серия`, сначала используй `doc-search`, а не company-fact `kb_search`.

## Как извлекать признаки в structured args

- Не ограничивайся только `query`, если из вопроса можно явно извлечь параметры.
- Для подбора и техвопросов старайся передавать признаки прямо в аргументы `corp_db_search`.
- Типичные соответствия:
  - вес -> `weight_kg_min` / `weight_kg_max`
  - Ra / CRI -> `cri_ra_min` / `cri_ra_max`
  - светораспределение / угол -> `beam_pattern`
  - климатическое исполнение -> `climate_execution`
  - класс электрозащиты -> `electrical_protection_class`
  - взрывозащита -> `explosion_protected`, `explosion_protection_marking`
  - род тока -> `voltage_kind`
  - номинальное/минимальное/максимальное напряжение -> `voltage_nominal_v_*`, `voltage_min_v_*`, `voltage_max_v_*`
  - габариты -> `dimensions_raw` или диапазоны `length_mm_*`, `width_mm_*`, `height_mm_*`
  - гарантия -> `warranty_years_min` / `warranty_years_max`
  - коэффициент мощности -> `power_factor_operator`, `power_factor_min_min` / `power_factor_min_max`

- Если запрос смешанный, используй оба канала:
  - `query` оставь как короткое смысловое описание задачи;
  - явные технические признаки вынеси в structured поля.

## Примеры

```json
{"kind":"hybrid_search","profile":"entity_resolver","query":"LAD LED LINE OZ 25"}
```

```json
{"kind":"sku_by_code","etm":"LINE1132"}
```

```json
{"kind":"lamp_filters","category":"складские помещения","ip":"IP65","power_w_min":20,"power_w_max":60,"mounting_type":"подвес"}
```

```json
{"kind":"hybrid_search","profile":"candidate_generation","query":"подбери модель по характеристикам","beam_pattern":"60°","weight_kg_max":18.3,"dimensions_raw":"774 x 428 x 406 мм"}
```

```json
{"kind":"application_recommendation","query":"подбери освещение для спортивного стадиона","limit_categories":3,"limit_lamps":3,"limit_portfolio":2}
```

```json
{"kind":"application_recommendation","query":"подбери мощный светильник для карьерна","limit_lamps":3,"ip":"IP67"}
```

```json
{"kind":"hybrid_search","profile":"candidate_generation","query":"нужен взрывозащищённый светильник","explosion_protected":true,"explosion_protection_marking":"1Ex mb IIС T6 Gb X","power_w_min":35,"power_w_max":35,"voltage_nominal_v_min":230,"voltage_nominal_v_max":230,"cct_k_min":5000,"cct_k_max":5000}
```

## Как отвечать

- Возвращай пользователю только результат, без упоминания SQL, DSN, таблиц и внутренней инфраструктуры.
- Если результатов нет, предложи уточнить код, диапазон параметров или сферу применения.
- Если БД недоступна, прямо скажи об этом и переключись на `doc-search` только там, где это уместно по смыслу вопроса.

## Что делать после `empty`

- Не останавливайся после первого `empty`, если вопрос допускает ещё один осмысленный заход.
- Для `entity_resolver`:
  - сократи запрос до серии, кода, артикула или ключевого названия;
  - если виден ETM/ORACL или похожий код, попробуй `sku_by_code`;
  - если это всё-таки вопрос про правила, гарантию, контакты или общий текстовый контекст, переключись на `doc-search`.
- Для `candidate_generation`:
  - попробуй второй запрос только из сильных токенов: `IP65`, `5000K`, `25Вт`, серия, тип крепления, сфера;
  - если из текста можно извлечь параметры, используй `lamp_filters` или `hybrid_search` с явными structured filter args;
  - после найденных кандидатов при необходимости добери `related_evidence`.
- Для запросов про сферу/портфолио:
  - сократи запрос до ключевой отрасли или объекта (`нефтегаз`, `склад`, `АЗС`);
  - для broad-object подбора сначала пробуй `application_recommendation`;
  - если он дал `empty`, затем используй `portfolio_by_sphere` или `related_evidence`.
- Примеры второго шага:
  - `нефтегазовые проекты портфолио` -> `hybrid_search related_evidence query="нефтегаз"` -> при необходимости `doc-search`
  - `прожектор 100 ватт ip65` -> `hybrid_search candidate_generation` -> `lamp_filters ip=IP65 power_w_min=85 power_w_max=115`
  - `нужен светильник 709 Вт 220 В 154-308 В 5 лет` -> `hybrid_search entity_resolver` + `power_w_min/max`, `voltage_nominal_v_*`, `voltage_min_v_*`, `voltage_max_v_*`, `warranty_years_*`
  - `нужен Ra 80 УХЛ 4 / 3.1 класс II 15 Вт` -> `hybrid_search candidate_generation` + `cri_ra_*`, `climate_execution`, `electrical_protection_class`, `power_w_*`
  - `гарантия на светильники` -> если БД не дала ответ, перейти в `doc-search`
