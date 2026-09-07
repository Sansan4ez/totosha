# RFC-030: последовательность реализации для оркестратора

Эпик: `totosha-m911`. Источник: [RFC-030](../rfc/RFC-030-capability-registry-and-atomic-llm-planning.md).
Подготовлено 2026-09-07. Это план, **не разрешение на запуск или deployment**. RFC остаётся Proposed.
Машиночитаемый порядок: [rfc030-orchestrator-order.json](rfc030-orchestrator-order.json).

## Проверка графа

- Проверены `br show --json` всех 42 executable tasks и их блокирующие зависимости: каждый blocker стоит раньше в порядке; циклов нет.
- На момент подготовки все 42 задачи `open`, stranded `in_progress` отсутствуют. Это snapshot, не гарантия состояния перед будущим запуском.
- `totosha-m911` — epic, `totosha-i0zf` — deferred cleanup umbrella. Оба исключены из worker queue; три cleanup descendants включены.
- `related` links к legacy fixes не являются prerequisites; `parent-child` — группировка, а не разрешение закрыть родителя.
- Граф не переписан ради последовательности: дополнительные review/live barriers ниже строже технических `blocks`.

## Порядок раундов

Один tmux run = один раунд. Внутри раунда workers строго последовательны; после раунда — review и осознанный запуск следующего. Не объединять все раунды в unattended deployment.

### r01-inventory-holdout: Inventory и независимый holdout

1. `totosha-m911.1` — Зафиксировать route→executor→schema и inventory routing-сложности
1. `totosha-m911.3` — Заморозить независимый held-out набор и рубрики четырёх слоёв качества

**Условие запуска / остановки:** Review scope RFC и независимой разметки; без production изменений.

### r02-live-baseline: Frozen live baseline

1. `totosha-m911.2` — Добавить repeated-run runner и заморозить production baseline

**Условие запуска / остановки:** Подтвердить pinned endpoint/models, доступ к baseline stack, стоимость и время реальных прогонов. Не продолжать без сохранённого baseline.

### r03-contracts-planner: Security ingress, registry, contracts, CI и planner

1. `totosha-m911.15` — Подключить hard ingress gate перед любым planner/shadow вызовом
1. `totosha-m911.4` — Реализовать capability registry loader и allowlisted executor bindings
1. `totosha-m911.5` — Описать reviewed capability specs, полные input schemas и canonical catalogs
1. `totosha-m911.7` — Реализовать строгую canonicalization и validation effective arguments
1. `totosha-m911.8` — Ввести normalized result schema и безопасную evidence projection
1. `totosha-m911.6` — Генерировать selector-visible contracts без потери семантики
1. `totosha-m911.12` — Создать allowlisted deterministic dispatcher и bounded result handling
1. `totosha-m911.36` — Добавить CI validation registry, schema parity и ownership contracts
1. `totosha-m911.9` — Формировать ограниченный session context и immutable answer envelope
1. `totosha-m911.10` — Реализовать atomic planner и не более одного schema-local repair

**Условие запуска / остановки:** Review baseline/holdout и consolidation hypothesis. Завершить и проверить полные schemas; при неподходящем объёме разбить задачу до запуска, а не закрывать частично.

### r04-provider-contract: Контракт production provider

1. `totosha-m911.11` — Проверить actual structured-output контракт pinned provider/model

**Условие запуска / остановки:** Отдельно разрешить live provider probes и расходы. Schema/model mismatch блокирует продолжение; fake tests не заменяют live checks.

### r05-isolated-pipeline: Workspace isolation, finalizer и полная новая pipeline

1. `totosha-m911.16` — Запретить корпоративные инструменты в workspace delegation profile
1. `totosha-m911.17` — Изолировать workspace shell/filesystem/network от corporate corpus
1. `totosha-m911.13` — Реализовать no-tools evidence-grounded finalizer
1. `totosha-m911.14` — Добавить reviewed outcome templates и evidence-only аварийный renderer
1. `totosha-m911.18` — Собрать изолированный full capability pipeline с единственной workspace entry action
1. `totosha-m911.19` — Добавить canonical capability telemetry и DB/LLM call accounting

**Условие запуска / остановки:** Security review tool + shell/filesystem/network boundary. Изоляцию проверять в выделенном test stack; изменения production mounts/network требуют отдельного разрешения.

### r06-shadow-canary-control: Shadow, compatibility, quality reports и canary control

1. `totosha-m911.20` — Ввести взаимно исключающие pipeline modes и planner-only shadow
1. `totosha-m911.21` — Реализовать versioned legacy aliases только для telemetry и benchmarks
1. `totosha-m911.37` — Добавить независимые capability/evidence/answer оценки и dashboards
1. `totosha-m911.22` — Добавить admin canary coverage switch и full-pipeline rollback

**Условие запуска / остановки:** Review полной pipeline и telemetry. Coding/config support не означает разрешение включить live shadow/canary. Перед live запуском подтвердить cohort, stack и rollback.

### r07-table-slices: Первые четыре table vertical slices

1. `totosha-m911.23` — Вертикаль catalog_documents.lookup: bounded batch и per-item evidence
1. `totosha-m911.24` — Вертикаль catalog_codes.lookup: forward/reverse SKU/ETM/ORACL
1. `totosha-m911.25` — Вертикаль mountings.lookup: варианты и named compatibility
1. `totosha-m911.26` — Вертикаль sphere_categories.lookup: только curated user-visible mapping

**Условие запуска / остановки:** Provider/pipeline/contracts/evaluation gates green. Review первой documents вертикали перед следующей при обнаружении общего contract defect; все slices проходят новый путь целиком.

### r08-strict-catalog: Catalog exact/structured/hybrid и canary vertical

1. `totosha-m911.27` — Реализовать strict catalog exact/structured стратегии без filter relaxation
1. `totosha-m911.28` — Добавить catalog hybrid ranking и showcase внутри жёстких constraints
1. `totosha-m911.29` — Включить catalog_lamps.search в полную canary вертикаль

**Условие запуска / остановки:** После table-slice review. В v3 ни один power/category constraint не ослабляется; legacy остаётся работоспособным для rollback.

### r09-company-knowledge: Source-scoped knowledge и grounded vertical

1. `totosha-m911.30` — Реализовать source-scoped knowledge handler и честный coverage contract
1. `totosha-m911.31` — Включить company knowledge в вертикаль без subtype rewrites

**Условие запуска / остановки:** После catalog review. Отдельно проверить domain/facets, partial company facts и отсутствие company/series fallback.

### r10-remaining-workflows: Portfolio, corpus и recommendation; full coverage

1. `totosha-m911.32` — Вертикаль portfolio.search: named object и sphere с bounded evidence
1. `totosha-m911.33` — Вертикаль document_corpus.search по concrete indexed domains
1. `totosha-m911.34` — Реализовать bounded application recommendation workflow handler
1. `totosha-m911.35` — Включить recommendation workflow и закрыть remaining corporate coverage

**Условие запуска / остановки:** После knowledge review. Сверить original route inventory: ни один корпоративный entry point не потерян и не ушёл в ReAct.

### r11-live-acceptance: Полный quality/security/performance gate

1. `totosha-m911.38` — Пройти полный pinned-model quality/security/performance acceptance gate

**Условие запуска / остановки:** Явное разрешение live прогонов и бюджета; независимые reviewers/labels доступны, held-out не использован для tuning. Минимум 3×100% prod-agent и >=10 повторов stability case.

### r12-primary-cutover: Primary cutover и pre-cleanup rollback drill

1. `totosha-m911.39` — Выполнить primary cutover и проверить rollback до cleanup

**Условие запуска / остановки:** STOP: отдельное разрешение оператора на production deployment после review acceptance artifacts. Проверить retained release digest/config и доступность rollback. Не запускать автоматически за r11.

### r13-cleanup: Удаление legacy после verified cutover

1. `totosha-i0zf.1` — Удалить legacy intent ordering, split planner и semantic argument rewrites
1. `totosha-i0zf.2` — Удалить fallback graphs, route evidence grading и corporate ReAct shortlist
1. `totosha-i0zf.3` — Удалить migration telemetry/config и опубликовать net-deletion/rollback отчёт

**Условие запуска / остановки:** STOP: отдельное разрешение Phase 6 после наблюдения primary и проверки rollback. Оператор снимает deferred с umbrella totosha-i0zf только после review; umbrella не передаётся worker. Post-cleanup rollback — deployment retained artifact, не runtime switch.

## Подготовка запуска

1. Оператор создаёт отдельную feature branch/worktree от согласованного baseline. Не использовать общий `develop` как единственный рабочий deployment tree. Рабочее дерево чистое, Beads JSONL tracked/synced.
2. Проверить отсутствие активного control/worker и `.git/br-orchestrator/stale-worker` (реальный git-dir получать через `git rev-parse --absolute-git-dir`). Не удалять stale marker до диагностики.
3. Проверить инструменты `br`, `bv`, `tmux`, `python3`, исполняемый agent wrapper и его readiness/session-id handshake. Не создавать repo-specific копию control program.
4. Повторно прочитать задачу и реальные blockers для каждого ID; закрытые executable tasks можно пропустить после проверки артефактов. Новый blocker/review finding требует пересмотра порядка.
5. Проверить live approval и бюджет раунда. Baseline, provider probes, container isolation и final acceptance требуют реальных зависимостей. При недоступности остановиться, не закрывать задачу фиктивным pass.
6. Worker: ровно одна issue, один локальный non-merge commit с exact issue ID отдельным token и синхронизированным `.beads/issues.jsonl`; clean tree на выходе. Не менять branch, не amend, не запускать других workers, не закрывать epic/umbrella, **не merge/push**. Публикация — граница оператора, несмотря на общий session checklist репозитория.
7. Для задач с deployment/rollback получать явное разрешение до запуска worker. Если scope не укладывается в один законченный deliverable/commit, вернуть на decomposition до запуска.

Доступные команды этой установленной версии `br`:

```bash
br list --status=in_progress
br ready --parent totosha-m911 --recursive --limit 0
br dep tree totosha-m911 --direction up --max-depth 3
br show totosha-m911.1 --json
br dep list totosha-m911.1 --json
br dep cycles
```

`br ready --epic` в текущей версии не поддерживается. Пустой ready set не доказывает завершение эпика.

## Команда одного запуска (только после approval)

Ниже шаблон для Bash. Каждый вызов запускает **только один** выбранный раунд из JSON; это не bulk scheduler. Подставить согласованные repo/wrapper и уникальное имя. Control сам по себе не заменяет проверку dependency order оркестратором.

```bash
REPO=/path/to/approved/feature-worktree
SKILL=/home/admin/.pi/agent/skills/tmux-br-orchestrator
WRAPPER="$SKILL/examples/pi-wrapper.sh"
ROUND=r01-inventory-holdout
RUN="rfc030-${ROUND}-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM"

# До этой команды: approvals, live br blockers, clean tree, branch и wrapper проверены.
mapfile -t ISSUES < <(python3 - "$REPO" "$ROUND" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]) / "docs/operations/rfc030-orchestrator-order.json"
plan = json.loads(p.read_text())
round_ = next(r for r in plan["rounds"] if r["run_suffix"] == sys.argv[2])
print("\n".join(round_["issues"]))
PY
)
(( ${#ISSUES[@]} > 0 )) || exit 1
python3 "$SKILL/scripts/orchestrator.py" launch \
  --repo "$REPO" --agent-script "$WRAPPER" \
  "$RUN" totosha-m911 "${ISSUES[@]}"
```

Успешный возврат `launch` означает лишь старт detached run. Фактический результат — `status=ok` и проверенный manifest.
При длинных live gates оператор заранее задаёт `BR_ORCHESTRATOR_RUN_TIMEOUT_SECONDS` по ожидаемому времени одной issue, не снимая остальные invariants.

## Review, ошибки и закрытие

- После каждого раунда прочитать `<git-dir>/br-orchestrator/runs/<run>/status`, `manifest.jsonl`, `control.log` и review range; сверить issue→session→commit и выполненные тесты.
- Review findings создавать дочерними issues эпика. Если finding блокирует следующие задачи, добавить настоящий `blocks`, выполнить отдельный fix round с новым именем и пересчитать остаток очереди.
- Failure/timeout: не запускать следующую issue; проверить worker process group, dirty tree, branch/HEAD, claim и stale marker. Не сбрасывать claim, пока worker может работать. Resume только после явной reconciliation.
- Не маскировать failing held-out case изменением ожиданий. После tuning по held-out нужен новый независимый acceptance set.
- После `totosha-i0zf.3` отдельно проверить и закрыть cleanup umbrella `totosha-i0zf`, затем только по явному запросу оператора провести epic finalization: все descendants/findings закрыты, полные gates/review/rollback подтверждены, workers отсутствуют, дерево чистое.
- Закрытие umbrella/эпика — отдельные локальные coordination/finalization commits; они не подаются normal worker и не входят в 42 issue commits. Merge/push выполняет оператор.

## Почему порядок отличается от номеров

- Inventory и held-out идут до настройки prompt; реальные baseline измерения изолированы approval-раундом.
- CI `.36` идёт сразу после contracts/dispatcher, а не после реализации всех capabilities.
- Provider `.11` проверяется до сборки дорогих live vertical slices.
- Quality evaluator `.37` готов до canary, чтобы видеть регрессии сразу, а не после cutover.
- General workspace isolation завершена до единственного delegation entry point.
- Cleanup технически и операционно отделён от primary: до cleanup rollback переключает whole pipeline, после — разворачивает retained release artifact.
