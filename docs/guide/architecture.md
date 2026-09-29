# Архитектура (обзор для разработчика)

Краткий обзор для тех, кто будет читать или менять код. Полное проектное решение — в
`docs/hld/`, начиная с [`00-decisions.md`](../hld/00-decisions.md), которое фиксирует каждое
сквозное решение (D1…D35); этот файл его не заменяет, а только даёт координаты. Спецификация
владельца — [`docs/SPEC.md`](../SPEC.md) (закон, не редактируется).

## Компоненты и где что лежит

```
frontend/       консоль на Vite + React + TypeScript (интерфейсы оператора/ДДС/инструктора/отчёта)
backend/        FastAPI-приложение, пакет `app`:
  app/api/          HTTP/WebSocket-роутеры, DI-контейнер
  app/domain/       чистый Python + Pydantic: типы, состояние симуляции, правила оценки — без I/O
  app/application/  сценарии использования, порты (Protocol), Unit of Work, движок мировых событий
  app/infrastructure/  реализации портов: Postgres/SQLAlchemy, Redis, LiveKit-клиент
  app/inference/    реализации портов для ASR/LLM/TTS/VAD-провайдеров
  app/db/           модели SQLAlchemy, миграции Alembic
  app/config/       настройки (`Settings`), профили моделей
  app/cli/, app/tools/  консольные команды (preflight, seed_users, import_scenarios, …)
workers/
  voice_agent/  процесс голосового агента (пакет `voice_agent`), зависит от `app` как от библиотеки
  tts_qwen3/    отдельный GPU-воркер Qwen3-TTS — свой venv, свой образ, никогда не член workspace
scenarios/      содержимое сценариев (schemas/, examples/, tickets/)
infra/          Docker Compose (dev/test/полный стенд), конфигурация LiveKit, скрипты запуска
docs/           SPEC.md, hld/ (проектные решения), guide/ (этот раздел), RUNBOOK.md
```

## Слои и правило импортов (HLD 00 D2)

```
api            -> application -> domain
infrastructure -> application, domain      (реализует порты)
inference      -> application, domain      (реализует порты)
voice_agent    -> application, inference, infrastructure
```

`app/domain` не импортирует FastAPI, SQLAlchemy, LiveKit, Redis, httpx; никакого I/O, системного
времени или `random` на уровне модуля — время и случайность передаются аргументами, что делает
симуляцию воспроизводимой. `app/application` не импортирует `infrastructure`, `inference`-адаптеры,
`api` или SDK вендоров. Правило проверяется автоматически: `backend/tools/check_imports.py`
(`make boundaries` / часть `make gate`) статически (`ast`) находит любой запрещённый импорт —
это часть архитектуры, а не рекомендация.

## Четыре слоя информации — четыре типа и четыре места хранения (HLD 00 D3)

| Слой | Тип домена | Где хранится | Кто пишет |
|:--|:--|:--|:--|
| Истина сценария (WorldTruth) | `WorldTruth` | `incident_world_states` | инстанцирование сценария, движок мировых событий |
| Убеждения заявителя (CallerBelief) | `CallerBelief` | `incident_caller_beliefs` | инстанцирование сценария, движок мировых событий |
| Карточка оператора (OperatorCard) | `OperatorCard` | `incident_cards` + `incident_card_revisions` | только команды стажёра |
| Передача в ДДС (HandoffSnapshot) | `HandoffSnapshot` | `handoff_snapshots`, неизменяемая (БД отклоняет UPDATE/DELETE триггером) | только сценарий передачи, копия OperatorCard по значению |

Ни один тип не наследуется от другого и не хранит ссылку на другой — преобразование между слоями
всегда явная глубокая копия внутри одного именованного сценария использования. Видимость каждой
роли (что показывать стажёру, преподавателю, отчёту) строится по структуре данных, а не по
соглашению «не присылать это поле» — так вычислено, что стажёру-оператору нельзя увидеть истину
сценария или карточку в разделе, куда её ещё не передали.

## Потоки данных

- **Команды и HTTP.** REST — контракт `docs/hld/openapi.yaml`; правило слоёв гарантирует, что
  каждый роутер идёт через `application`, а не напрямую в БД.
- **Реальное время.** Два независимых канала (HLD 40), которые никогда не смешиваются: медиа
  (микрофон и голос заявителя) — WebRTC через LiveKit; события приложения (`SessionEvent`,
  изменения статусов, ходы диалога) — свой WebSocket
  (`GET /api/v1/ws/sessions/{session_id}?token=<JWT>`), с одним и тем же
  Postgres-как-источник-истины/Redis-как-fan-out контуром для аудита и рассылки. Сырой звук
  никогда не идёт через REST или через этот WebSocket.
- **Голосовой путь** (HLD 50): VAD → ASR → диалог (интерпретатор → шлюз → генератор → валидатор,
  HLD 00 D10) → TTS, каждый этап — порт с провайдером `fake`/`energy` для тестов и реальным
  провайдером (Silero, GigaAM, локальная LLM через `llama-server`, Qwen3-TTS/Piper) для прогона на
  GPU. Процесс `voice_agent` выполняет этот путь, переиспользуя `application`-слой `app` в своём
  процессе (workspace-зависимость, не HTTP-вызов).
- **Оценка и отчёт** (HLD 00 D11): события сессии — источник правды для баллов; отчёт строится
  из журнала событий, а не пересчитывается «на глаз» интерфейсом.

## Фронтенд (HLD 00 D12)

`frontend/src` — по функциональным срезам: `app/` (маршруты, `router.tsx`), `entities/` (общие
модели — сессия, звонок, сценарий…), `features/` (экран/фича — `dds/`, `operator/`, `instructor/`,
`admin/`, `report/`, `lesson/`, …), `shared/` (API-клиент, i18n, UI-компоненты). Все пользовательские
строки — по-русски, в `frontend/src/shared/i18n/ru.ts`; контракт с бэкендом —
`frontend/src/shared/api/schema.d.ts`, регенерируется из `openapi.yaml` (`npm run gen:api`) —
руками не редактируется.

## Тестирование (HLD 00 D13)

`make gate` = ruff → mypy (`domain`, `application`) → проверка границ импорта → валидация
сценариев → pytest (юнит- и интеграционные, на реальных тестовых Postgres/Redis из
`infra/docker-compose.test.yml`) → фронтенд (`tsc --noEmit`, vitest, `vite build`). Гейт намеренно
не использует GPU и реальные модели — только провайдеры `fake`/`energy`; прогон с реальными
моделями — отдельные бенчмарки (`benchmarks/`, `make bench-*`), никогда не часть гейта.

## Куда смотреть дальше

- [`docs/hld/00-decisions.md`](../hld/00-decisions.md) — все сквозные решения одним файлом.
- [`docs/hld/10-domain-model.md`](../hld/10-domain-model.md) — домен и каталог событий.
- [`docs/hld/20-db-schema.md`](../hld/20-db-schema.md) — схема базы данных.
- [`docs/hld/30-scenario-format.md`](../hld/30-scenario-format.md) — формат файлов сценариев.
- [`docs/hld/40-realtime-protocol.md`](../hld/40-realtime-protocol.md) — WebSocket, переподключение.
- [`docs/hld/50-voice-pipeline.md`](../hld/50-voice-pipeline.md) — голосовой путь.
- [`docs/hld/60-inference-ops.md`](../hld/60-inference-ops.md) — профили моделей, эксплуатация вывода.
- [`docs/hld/openapi.yaml`](../hld/openapi.yaml) — REST-контракт.
- [`docs/RUNBOOK.md`](../RUNBOOK.md) — эксплуатация уже развёрнутого стенда.
