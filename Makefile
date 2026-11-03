# MOODY BLUES developer commands. Run `make help`.
SHELL := /bin/bash
.DEFAULT_GOAL := help

UV      ?= uv
PNPM    ?= pnpm
FE      := frontend
PYTEST  := $(UV) run pytest

.PHONY: help setup dev dev-backend dev-frontend lint format typecheck test test-integration \
        test-e2e build check doctor world-demo docker-smoke vultr-smoke vultr-models sandbox-clean clean

help: ## List commands
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

setup: ## Install Python + Node deps (from lockfiles) and the Playwright browser
	$(UV) sync --frozen
	$(PNPM) --dir $(FE) install --frozen-lockfile
	$(PNPM) --dir $(FE) exec playwright install chromium

dev: ## Run backend (:8000) and frontend (:3000) together; Ctrl-C stops both
	@trap 'kill 0' EXIT INT TERM; \
	$(MAKE) --no-print-directory dev-backend & \
	$(MAKE) --no-print-directory dev-frontend & \
	wait

dev-backend: ## Run FastAPI with reload on :8000
	$(UV) run uvicorn moody_blues.main:app --reload --reload-dir backend --host 127.0.0.1 --port 8000

dev-frontend: ## Run Next.js dev server on :3000
	$(PNPM) --dir $(FE) dev --hostname 127.0.0.1 --port 3000

lint: ## Ruff format check + lint, ESLint
	$(UV) run ruff format --check backend tests
	$(UV) run ruff check backend tests
	$(PNPM) --dir $(FE) lint

format: ## Auto-format and auto-fix Python
	$(UV) run ruff format backend tests
	$(UV) run ruff check --fix backend tests

typecheck: ## Pyright (strict) + tsc
	$(UV) run pyright
	$(PNPM) --dir $(FE) typecheck

test: ## Unit + World Engine tests (offline; real SQLite; no Docker, no network)
	$(PYTEST) tests/unit tests/world

test-integration: ## Docker sandbox integration + containment tests (needs a Docker daemon)
	$(PYTEST) tests/integration tests/security -m docker

build: ## Production build of the frontend
	$(PNPM) --dir $(FE) build

test-e2e: build ## Playwright against the real backend + production frontend build
	$(PNPM) --dir $(FE) test:e2e

check: lint typecheck test test-integration test-e2e ## Everything except live Vultr calls

doctor: ## Diagnose local prerequisites and configuration (makes no chargeable calls)
	$(UV) run moody-blues doctor

world-demo: ## Run the World Engine reference cases (real SQLite; offline; free)
	$(UV) run moody-blues world-demo

docker-smoke: ## Run the fixed smoke program in a real disposable container
	$(UV) run moody-blues docker-smoke

vultr-smoke: ## LIVE + CHARGEABLE: basic inference and tool calling against Vultr
	$(UV) run moody-blues vultr-smoke

vultr-models: ## LIVE: list models visible to the configured Vultr key
	$(UV) run moody-blues vultr-models

sandbox-clean: ## Force-remove any leftover sandbox containers
	@ids=$$(docker ps -aq --filter label=io.moody-blues.sandbox); \
	if [ -n "$$ids" ]; then docker rm -f $$ids; else echo "no sandbox containers"; fi

clean: ## Remove caches and build output (literal paths only)
	rm -rf .pytest_cache .ruff_cache frontend/.next frontend/playwright-report frontend/test-results
