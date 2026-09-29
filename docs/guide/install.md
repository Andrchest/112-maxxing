# Развёртывание

Это — путь «с нуля» (свежий `git clone`) до работающего демо-стенда. Для повседневной эксплуатации
уже развёрнутого стенда (старт/стоп, preflight, сброс демо-данных, устранение неполадок,
переключение профиля модели) см. [../RUNBOOK.md](../RUNBOOK.md) — этот файл его не дублирует.
Общее устройство системы — [architecture.md](architecture.md) и [../hld/](../hld/).

## Требования

- Linux-хост, Docker с Docker Compose (`infra/docker-compose.yml` — семь сервисов SPEC §36 плюс
  дополнительный `tts-qwen3` за отдельным профилем компоуза).
- Для реальных голосовых моделей — GPU с поддержкой NVIDIA runtime. Профиль по умолчанию,
  `DEV_3060TI`, рассчитан на карту вида **RTX 3060 Ti (8 ГБ видеопамяти)**; без GPU (либо с
  фиктивными провайдерами) тренажёр работает, но без звука — см.
  [README.md](README.md#ограничения-стенда).
- Python **3.12**, менеджер пакетов **uv** — для сборки бэкенда (`backend/`, `workers/voice_agent`,
  `benchmarks`, один `uv.lock` на всё это как на один workspace).
- Node.js/npm — для сборки консоли (`frontend/`).

## Первичная настройка

```
git clone <repo> && cd 112-maxxing
cp .env.example .env         # каждое значение внутри — заглушка, пока вы его не замените
make deps                    # uv sync (backend workspace, --inexact) + npm ci (frontend)
```

`.env` — единственное место, откуда стенд читает секреты и настройки (кроме
`infra/.env.profile`, который генерируется командой, — его руками не редактируют). Ключевые
переменные, которые обязательно нужно сменить перед реальным использованием:

| Переменная | Назначение |
|---|---|
| `SIM_JWT_SECRET` | секрет подписи токенов входа |
| `SIM_SEED_TRAINEE_PASSWORD`, `SIM_SEED_INSTRUCTOR_PASSWORD`, `SIM_SEED_ADMIN_PASSWORD` | пароли трёх учётных записей, которые создаёт `make seed-users` |
| `SIM_LIVEKIT_API_KEY`, `SIM_LIVEKIT_API_SECRET` | ключи комнаты реального времени (голос, звонки) |
| `SIM_MODEL_PROFILE` | какой профиль модели используется (см. [«Профили моделей»](#профили-моделей)) |
| `SIM_CORS_ALLOW_ORIGINS` | список разрешённых источников для API — JSON-список, файл нельзя `source`'ить (см. ниже) |

**Никогда не делайте `source .env`** — настройки читает сам процесс (`SIM_ENV_FILE`), а
`set -a && . ./.env` ломает переменные-списки в формате JSON (`SIM_CORS_ALLOW_ORIGINS` и
подобные) с ошибкой `SettingsError: error parsing value for field "cors_allow_origins"`. Исключение
— `infra/.env.profile`: простой файл `ИМЯ=значение`, который пишет `make profile-env` и который
источники `make run-*` подключают сами.

## Основные команды (`make`)

| Команда | Что делает |
|---|---|
| `make deps` | `uv sync` (бэкенд, `--inexact`) + `npm ci` (консоль) |
| `make certs` | локальный центр сертификации и сертификат сервера для HTTPS (`infra/certs/`) — нужен для профиля `tls`, см. «HTTPS и сертификаты» в [admin.md](admin.md) |
| `make seed-users` | создаёт/обновляет (upsert по логину) три учётные записи: `trainee`, `instructor`, `admin` — пароли из `SIM_SEED_*_PASSWORD` |
| `make seed-materials` | загружает организаторские методические файлы в «Справочную базу» (идемпотентно, требует предварительного `make seed-users`) |
| `make demo-init` | `migrate` + `seed-users` + импорт `scenarios/examples` — весь путь «с нуля до демо-данных» одной идемпотентной командой |
| `make up` | поднимает полный стенд (семь сервисов SPEC §36; `TTS_COMPOSE_PROFILE=qwen3-tts make up` добавляет восьмой) |
| `make preflight` | все проверки готовности (модели, база данных, Redis, LiveKit, GPU — см. [«Проверка готовности»](#проверка-готовности)) |
| `make down` | останавливает стенд; данные (Postgres, записи разговоров) сохраняются |
| `make backup-now` | резервная копия базы данных и записей прямо сейчас |
| `make backup-verify` | проверяет, что последняя резервная копия свежая и успешная |
| `make restore FILE=… [RECORDINGS=…]` | восстановление из резервной копии |

Полный путь «с нуля до демо»:

```
make deps
make models          # веса профиля DEV_3060TI + сэмпл для прогрева (гигабайты, один раз)
make demo-init        # migrate + seed-users + импорт scenarios/examples
make up               # семь сервисов
make preflight        # проверка готовности
```

## Профили моделей

`SIM_MODEL_PROFILE` в `.env` выбирает файл `backend/app/config/profiles/<имя>.yaml`, который
задаёт пути к весам и параметры запуска `llama-server` для этой конфигурации железа —
например, `DEV_3060TI` (LLM и ASR/TTS на GPU) или `DEV_3060TI_SHARED` (тот же LLM на GPU, но
ASR/TTS на CPU — для случая, когда видеопамять делит с чем-то ещё). Переключение профиля:

1. Изменить `SIM_MODEL_PROFILE` в `.env`.
2. Если новому профилю нужны веса, которых ещё нет — `make models` (или конкретные
   `models-llm-qwen35`, `models-tts-qwen3` и т. п.).
3. `make up` заново (перегенерирует `infra/.env.profile`) — сервисы, читающие профиль
   только при старте (`llama-server`, `voice-agent`, `tts-qwen3`), нужно перезапустить.
4. `make preflight` — подтвердить, что профиль поднялся зелёным, прежде чем начинать занятие.

Подробности — раздел «Switching a model profile» в [../RUNBOOK.md](../RUNBOOK.md) и
`docs/benchmarks/models.md`.

## Проверка готовности

```
make preflight                                      # обычный вывод PASS/FAIL/SKIP по каждой проверке
make preflight ARGS='--profile DEV_3060TI --json'    # флаги передаются как есть
```

Проверяет по очереди GPU, наличие файлов моделей, ответ LLM/ASR/TTS, базу данных, Redis, LiveKit —
всего 11(+1) проверок SPEC §38. Запускайте после каждого `make up`/старта на хосте, а также после
снятия критического отказа модели или смены профиля. `fake`/`energy`-провайдеры (значения по
умолчанию в `.env.example`) всегда проходят проверку тривиально и ничего не доказывают о реальном
голосовом пути — для реального прогона нужны настоящие значения `SIM_VAD_PROVIDER`,
`SIM_ASR_PROVIDER`, `SIM_LLM_PROVIDER`, `SIM_TTS_PROVIDER`, `SIM_CALL_TRANSPORT` (раздел «Fresh
clone to a working demo» в корневом [README](../../README.md) перечисляет нужные значения).

Дальнейшая эксплуатация — старт/стоп, сброс демо-данных, устранение неполадок вида «звонок не
проходит», снятие критического отказа модели, HTTPS в классе, SIP, резервное копирование — в
[../RUNBOOK.md](../RUNBOOK.md) и в разделе [admin.md](admin.md) этого руководства.
