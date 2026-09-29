#!/usr/bin/env bash
# I6 SCENARIOS: builds the hand-off bundle for a tester (an AI agent that drives a browser by
# looking at the screen) on another machine: the Russian scenario text from docs/test-scenarios/,
# a README on how to hand it over, and access.md with the stand's address and the three logins.
# The passwords are read at build time from the demo stand's env file (outside the repo; never
# written into the repo) and access.md is created with mode 600.
#
#   frontend/e2e/scenarios/build-bundle.sh [BUNDLE_DIR]         (make e2e-scenarios-bundle)
#   frontend/e2e/scenarios/build-bundle.sh --http [BUNDLE_DIR]  (make e2e-scenarios-bundle-http)
#
# I6 HTTP: --http builds the variant for the temporary tailnet-only http endpoint (owner request:
# "временно" http, phone/microphone off). It renders scenario text fresh with every `secureOnly`
# step OMITTED (step ids keep their SNN.MM — no renumbering, see dsl.ts/doc.ts) instead of copying
# docs/test-scenarios/ verbatim, defaults BUNDLE_DIR to .../e2e-bundle-http, and access.md's
# address to E2E_HTTP_BASE_URL. docs/test-scenarios/ and the plain https bundle are untouched.
#
# Env: DEMO_ENV (default /home/andreipc/112-demo/.env), E2E_BASE_URL (default the tailnet https
# demo), E2E_HTTP_BASE_URL (default the tailnet http demo, --http only).
set -euo pipefail

HTTP=0
if [ "${1:-}" = "--http" ]; then
  HTTP=1
  shift
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BUNDLE_DIR="${1:-$([ "$HTTP" = 1 ] && echo /home/andreipc/112-demo/e2e-bundle-http || echo /home/andreipc/112-demo/e2e-bundle)}"
DEMO_ENV="${DEMO_ENV:-/home/andreipc/112-demo/.env}"
if [ "$HTTP" = 1 ]; then
  # Port 10080, the manager's stated default, is on Chromium's and Firefox's built-in
  # restricted-port list (net::ERR_UNSAFE_PORT in every real browser) — 10081 is the port
  # 112-demo/start.sh actually opens; keep this in sync with it.
  BASE_URL="${E2E_HTTP_BASE_URL:-http://home-pc.tailca038a.ts.net:10081}"
else
  BASE_URL="${E2E_BASE_URL:-https://home-pc.tailca038a.ts.net:10443}"
fi
SOURCE="$ROOT/docs/test-scenarios"

env_value() {
  local value
  value="$(grep -E "^$1=" "$DEMO_ENV" | head -n 1 | cut -d= -f2-)"
  value="${value#\'}"
  value="${value%\'}"
  if [ -z "$value" ]; then
    echo "build-bundle: $1 is not set in $DEMO_ENV" >&2
    exit 1
  fi
  printf '%s' "$value"
}

[ -f "$SOURCE/00-instructions.md" ] || { echo "build-bundle: no $SOURCE (make e2e-scenarios-doc)" >&2; exit 1; }
[ -r "$DEMO_ENV" ] || { echo "build-bundle: cannot read $DEMO_ENV" >&2; exit 1; }

if [ "$HTTP" = 1 ]; then
  HTTP_SOURCE="$(mktemp -d)"
  trap 'rm -rf "$HTTP_SOURCE"' EXIT
  (cd "$ROOT/frontend" && SCENARIO_DOC_WRITE_HTTP=1 SCENARIO_DOC_HTTP_DIR="$HTTP_SOURCE" npx vitest run e2e/scenarios/doc.test.ts) >&2
  SOURCE="$HTTP_SOURCE"
fi

ADMIN_PASS="$(env_value SIM_SEED_ADMIN_PASSWORD)"
INSTRUCTOR_PASS="$(env_value SIM_SEED_INSTRUCTOR_PASSWORD)"
TRAINEE_PASS="$(env_value SIM_SEED_TRAINEE_PASSWORD)"

mkdir -p "$BUNDLE_DIR"
find "$BUNDLE_DIR" -maxdepth 1 -type f -name '*.md' -delete
cp "$SOURCE"/*.md "$BUNDLE_DIR"/

umask 077
cat > "$BUNDLE_DIR/access.md" <<EOF
# Доступ к стенду

- **Адрес стенда:** $BASE_URL (открывается только из сети tailscale).
- **Учётные записи:**

| Логин | Роль | Пароль |
|---|---|---|
| \`admin\` | Администратор | \`$ADMIN_PASS\` |
| \`instructor\` | Преподаватель (на экране «Инструктор») | \`$INSTRUCTOR_PASS\` |
| \`trainee\` | Стажёр (на экране «Стажёр») | \`$TRAINEE_PASS\` |

«Пароль преподавателя», «пароль администратора», «пароль стажёра» в сценариях — это пароли отсюда.
Учётные записи, которые сценарии создают сами, описаны в «Тестовых данных» каждого сценария.
EOF
chmod 600 "$BUNDLE_DIR/access.md"
umask 022

cat > "$BUNDLE_DIR/README.md" <<'EOF'
# Тестовые сценарии тренажёра 112 — комплект для проверяющего

Комплект — только текст: браузер и доступ к стенду по tailscale, больше ничего не нужно
(Node, Playwright и т. п. не требуются).

## Состав

- `00-instructions.md` — правила для проверяющего: как читать шаг, правило немедленной
  остановки («СЛОМАН на шаге SNN.MM»), формат итогового отчёта, оглавление.
- `S01.md` … `S17.md` — сценарии, каждый в своём файле: цель, что нужно перед началом, тестовые
  данные, таблица «Шаг | Что сделать | Должно быть видно», уборка.
- `access.md` — адрес стенда и логины/пароли трёх учётных записей (**секретно**: права 600, не
  пересылайте дальше и не публикуйте).

## Как передать агенту

1. Убедитесь, что машина агента в tailscale и в её браузере открывается адрес из `access.md`.
2. Дайте агенту `00-instructions.md` и `access.md`, затем сценарии — все или нужные, по одному
   файлу `SNN.md` на сценарий. Например:
   «Прочитай 00-instructions.md и access.md. Выполни сценарии S01–S17 строго по инструкции:
   при первом несовпадении останавливай сценарий, отмечай СЛОМАН с номером шага и переходи к
   следующему. В конце дай итоговую таблицу».
3. Один сценарий: дайте только `00-instructions.md`, `access.md` и, например, `S03.md`.

## Что значит результат

- **РАБОТАЕТ** — все шаги сценария прошли: всё, что перечислено в «Должно быть видно», было на
  экране.
- **СЛОМАН на шаге SNN.MM** — на этом шаге чего-то из «Должно быть видно» не было (или действие
  нельзя было выполнить). Сценарий на этом остановлен; отчёт говорит, что ожидалось, что было на
  экране вместо этого, и где снимок экрана. Остальные сценарии выполняются дальше — они
  независимы.

## Откуда текст

Текст создан из исполняемых сценариев репозитория (`frontend/e2e/scenarios`, `make
e2e-scenarios-doc`) и проверен автоматическим прогоном на этом стенде (`make e2e-scenarios`):
каждая строка «Должно быть видно» — это проверка, которая выполнялась. Обновить комплект:
`make e2e-scenarios-bundle`.
EOF

if [ "$HTTP" = 1 ]; then
  cat >> "$BUNDLE_DIR/README.md" <<'EOF'

## Внимание: этот комплект — для временного http-адреса

Адрес в `access.md` — временный, без TLS (http, не https). Телефон и микрофон ДДС по http не
работают: интерфейс сам их скрывает, показывая «Недоступно по http: телефон и микрофон работают
только по https-адресу». Поэтому шаги, которые проверяют телефон или микрофон (в комплекте по
https они помечены «(только https)»), из этого комплекта ПРОПУЩЕНЫ — номера шагов не менялись,
просто в таблице их нет (например, после S02.07 сразу может идти S02.09). Всё остальное (вход,
статусы ДДС, отчёты, администрирование, выгрузки) проверяется как обычно. Чтобы проверить телефон
и микрофон, используйте https-адрес и обычный комплект (`make e2e-scenarios-bundle`).
EOF
fi

echo "bundle: $BUNDLE_DIR"
ls -l "$BUNDLE_DIR"
