#!/usr/bin/env bash
# I6 SCENARIOS: builds the hand-off bundle for a tester (an AI agent that drives a browser by
# looking at the screen) on another machine: the Russian scenario text from docs/test-scenarios/,
# a README on how to hand it over, and access.md with the stand's address and the three logins.
# The passwords are read at build time from the demo stand's env file (outside the repo; never
# written into the repo) and access.md is created with mode 600.
#
#   frontend/e2e/scenarios/build-bundle.sh [BUNDLE_DIR]      (make e2e-scenarios-bundle)
#
# Env: DEMO_ENV (default /home/andreipc/112-demo/.env), E2E_BASE_URL (default the tailnet demo).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BUNDLE_DIR="${1:-/home/andreipc/112-demo/e2e-bundle}"
DEMO_ENV="${DEMO_ENV:-/home/andreipc/112-demo/.env}"
BASE_URL="${E2E_BASE_URL:-https://home-pc.tailca038a.ts.net:10443}"
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
- `S01.md` … `S16.md` — сценарии, каждый в своём файле: цель, что нужно перед началом, тестовые
  данные, таблица «Шаг | Что сделать | Должно быть видно», уборка.
- `access.md` — адрес стенда и логины/пароли трёх учётных записей (**секретно**: права 600, не
  пересылайте дальше и не публикуйте).

## Как передать агенту

1. Убедитесь, что машина агента в tailscale и в её браузере открывается адрес из `access.md`.
2. Дайте агенту `00-instructions.md` и `access.md`, затем сценарии — все или нужные, по одному
   файлу `SNN.md` на сценарий. Например:
   «Прочитай 00-instructions.md и access.md. Выполни сценарии S01–S16 строго по инструкции:
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

echo "bundle: $BUNDLE_DIR"
ls -l "$BUNDLE_DIR"
