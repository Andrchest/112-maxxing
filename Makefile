SHELL := /bin/bash
UV := uv
COMPOSE_TEST := docker compose -f infra/docker-compose.test.yml -p sim112test
export SIM_DATABASE_URL ?= postgresql+asyncpg://sim:sim@localhost:55432/sim_test
export SIM_REDIS_URL ?= redis://localhost:56379/0
export SIM_JWT_SECRET ?= test-only-secret
export SIM_REQUIRE_INFERENCE_READY ?= false

ALEMBIC := $(UV) run alembic -c backend/alembic.ini
# Throwaway database used only by `db-check` (never by the test suite).
SCRATCH_DB := sim_dbcheck
SCRATCH_DATABASE_URL := postgresql+asyncpg://sim:sim@localhost:55432/$(SCRATCH_DB)

export SIM_API_HOST ?= 127.0.0.1
export SIM_API_PORT ?= 8100

.PHONY: deps infra-up infra-down fmt lint typecheck boundaries scenarios migrate db-check run-api seed-users test-backend gate-backend gate-frontend gate test
deps:
	$(UV) sync --all-packages --group dev
	cd frontend && npm ci
infra-up:
	$(COMPOSE_TEST) up -d --wait
infra-down:
	$(COMPOSE_TEST) down -v
fmt:
	$(UV) run ruff format . && $(UV) run ruff check --fix .
lint:
	$(UV) run ruff format --check . && $(UV) run ruff check .
typecheck:
	$(UV) run mypy backend/app/domain backend/app/application
boundaries:
	$(UV) run python backend/tools/check_imports.py
scenarios:
	$(UV) run python -m app.tools.validate_scenarios scenarios/examples
	$(UV) run python -m app.tools.export_scenario_schema --check
# Apply the Alembic history to SIM_DATABASE_URL (HLD 20-db-schema.md, D5).
migrate:
	$(ALEMBIC) upgrade head
# Models-versus-migration drift check: upgrade a throwaway scratch database from scratch and let
# `alembic check` diff Base.metadata against it. The scratch database is dropped first so the run
# always starts from an empty schema.
db-check: infra-up
	$(COMPOSE_TEST) exec -T postgres psql -v ON_ERROR_STOP=1 -U sim -d postgres \
		-c 'DROP DATABASE IF EXISTS $(SCRATCH_DB) WITH (FORCE)' \
		-c 'CREATE DATABASE $(SCRATCH_DB)'
	$(ALEMBIC) -x url=$(SCRATCH_DATABASE_URL) upgrade head
	$(ALEMBIC) -x url=$(SCRATCH_DATABASE_URL) check
# Run the API (D8). `--factory` because `create_app` takes an optional Container (E7-A).
# The default port is 8100, NOT 8000/8001: those belong to another project on the dev machine.
run-api:
	$(UV) run uvicorn app.api.main:create_app --factory --host $(SIM_API_HOST) --port $(SIM_API_PORT)
# Idempotent upsert of the three local accounts. The passwords come from SIM_SEED_*_PASSWORD;
# there is no default and none is ever written in source (SPEC §41).
seed-users:
	$(UV) run python -m app.tools.seed_users
test-backend: infra-up
	$(UV) run pytest -q
gate-backend: lint typecheck boundaries scenarios db-check test-backend
gate-frontend:
	cd frontend && npm run check:api && npm run lint && npm run typecheck && npm run test -- --run && npm run build
gate: gate-backend gate-frontend
	@echo "GATE GREEN"
test: test-backend
