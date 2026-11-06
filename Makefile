# MOODY BLUES developer commands. Run `make help`.
SHELL := /bin/bash
.DEFAULT_GOAL := help

UV      ?= uv
PNPM    ?= pnpm
FE      := frontend
PYTEST  := $(UV) run pytest

.PHONY: design-lab test-design help setup dev dev-backend dev-frontend lint format typecheck test test-integration \
        test-e2e build check doctor world-demo docker-smoke vultr-smoke vultr-models agent-run agent-eval \
        experiment-demo experiment-test experiment-containment experiment-live experiment-recover \
        investigator-preflight investigator-demo investigator-test investigator-containment \
        investigator-live investigator-eval investigator-repro evidence-audit eval-freeze \
        eval-verify eval-run eval-repro eval-report eval-test recorded-export recorded-verify \
        live-budget sandbox-clean clean containment-report ledger-verify deploy-lint vultr-plan \
        test-hosted release release-check

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

test: ## Unit + World + Target Agent + experiment + Investigator + evaluation + explorer tests (offline; no network)
	$(PYTEST) tests/unit tests/world tests/agent tests/experiment tests/investigator tests/evaluation tests/explorer

test-integration: ## Docker sandbox integration + containment tests (needs a Docker daemon)
	$(PYTEST) tests/integration tests/security -m docker

design-lab: ## Local design lab on :3010 (needs make dev-backend; never deployed)
	cd $(FE) && $(PNPM) design:dev

test-design: ## Build the design lab, then browser-test it against the real recorded evidence (free)
	cd $(FE) && $(PNPM) test:design

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

SCENARIO ?= phantom-failure
CONFIG   ?= hardened
TRIALS   ?= 3

agent-run: ## LIVE + CHARGEABLE: one LLM Target Agent run (SCENARIO=, CONFIG=, MODEL=)
	$(UV) run moody-blues agent-run --scenario $(SCENARIO) --config $(CONFIG) $(if $(MODEL),--model $(MODEL))

agent-eval: ## LIVE + CHARGEABLE batch: needs CONFIRM=1 (TRIALS=, MODEL=)
	$(UV) run moody-blues agent-eval --trials $(TRIALS) $(if $(MODEL),--model $(MODEL)) $(if $(CONFIRM),--confirm-billable)

experiment-demo: ## Real sandbox + coordinator + world + Oracle; reference executors; no model; free
	$(UV) run moody-blues experiment-demo

experiment-test: ## Offline experiment runtime tests (scripted sandbox; no Docker; no network)
	$(PYTEST) tests/experiment

experiment-containment: ## Real Docker: experiment runtime and the 12 containment violations
	$(PYTEST) tests/integration/test_experiment_runtime.py tests/security/test_experiment_containment.py -m docker

CASE  ?= phantom-failure-duplicate
LIVE_MODEL ?= glm-5.3

experiment-live: ## LIVE + CHARGEABLE: one sandboxed experiment; needs CONFIRM=1 (CASE=, CONFIG=, LIVE_MODEL=)
	$(UV) run moody-blues experiment-live --case $(CASE) --config $(if $(filter command line,$(origin CONFIG)),$(CONFIG),baseline) --model $(LIVE_MODEL) $(if $(CONFIRM),--confirm-billable)

experiment-recover: ## Remove orphan sandboxes; close experiments whose coordinator died (free)
	$(UV) run moody-blues experiment-recover

TIER     ?= validation
STRATEGY ?= adaptive
PART     ?= both
EVAL_TRIALS ?= 1
REPEATS ?= 2

investigator-preflight: ## Verify image pin, containment and fail-closed output on this host (free)
	$(UV) run moody-blues investigator-preflight

investigator-demo: ## OFFLINE fixture model; real sandboxes, worlds and Oracle (free)
	$(UV) run moody-blues investigator-demo

investigator-test: ## Offline Investigator tests (fixture model; no Docker; no network)
	$(PYTEST) tests/investigator

investigator-containment: ## Real Docker: hostile generated programs and the full workflow
	$(PYTEST) tests/security/test_generated_code.py -m docker

investigator-live: ## LIVE + CHARGEABLE: one investigation; needs CONFIRM=1 (TIER=, STRATEGY=)
	$(UV) run moody-blues investigator-live --tier $(TIER) --strategy $(STRATEGY) $(if $(CONFIRM),--confirm-billable)

investigator-eval: ## LIVE + CHARGEABLE: paired tests + comparison; needs CONFIRM=1 (TIER=, PART=, EVAL_TRIALS=, REPEATS=)
	$(UV) run moody-blues investigator-eval --tier $(TIER) --part $(PART) --trials $(EVAL_TRIALS) --repeats $(REPEATS) $(if $(CONFIRM),--confirm-billable)

RUNS ?= 6

investigator-repro: ## LIVE + CHARGEABLE: rerun one generated program; needs CONFIRM=1 (EXPERIMENT=, RUNS=)
	$(UV) run moody-blues investigator-repro --experiment $(EXPERIMENT) --runs $(RUNS) $(if $(CONFIRM),--confirm-billable)

evidence-audit: ## Reclassify existing live evidence by eligibility (free; reads records only)
	$(UV) run moody-blues evidence-audit

eval-test: ## Offline evaluation tests (fixture sandbox; no Docker; no network)
	$(PYTEST) tests/evaluation

eval-freeze: ## Write the registered manifest and trial plan once (free; refuses to overwrite)
	$(UV) run moody-blues eval-freeze

eval-verify: ## Check the registration is committed and still matches the code (free)
	$(UV) run moody-blues eval-verify

SUITE ?= causal

eval-run: ## LIVE + CHARGEABLE: one registered suite; needs CONFIRM=1 (SUITE=causal|strategies|adaptation|followup)
	$(UV) run moody-blues eval-run --suite $(SUITE) $(if $(CONFIRM),--confirm-billable)

eval-repro: ## LIVE + CHARGEABLE: registered rerun under manifest limits; needs CONFIRM=1 (EXPERIMENT=, RUNS=)
	$(UV) run moody-blues eval-repro --experiment $(EXPERIMENT) --runs $(RUNS) $(if $(CONFIRM),--confirm-billable)

eval-report: ## Recompute results from the journals into docs/evaluations/sprint-06/results (free)
	$(UV) run moody-blues eval-report

recorded-export: ## Rebuild the curated recorded investigations from local .artifacts (free)
	$(UV) run moody-blues recorded-export

recorded-verify: ## Verify recorded investigations against the manifest and, if present, source (free)
	$(UV) run moody-blues recorded-verify

live-budget: ## Show the application-side spend ledger (an estimate; makes no calls)
	$(UV) run moody-blues live-budget

containment-report: ## Attempt harmless escapes on this host and write the labeled evidence (free)
	$(UV) run moody-blues containment-report

ledger-verify: ## Print the spend ledger's hash and totals, or fail if it is corrupt (free)
	$(UV) run moody-blues ledger-verify

deploy-lint: ## Shellcheck the deploy scripts and validate the Caddyfile (needs Docker; free)
	docker run --rm -v "$(CURDIR)/infra/vultr:/mnt:ro" -w /mnt koalaman/shellcheck:stable -x -S warning -e SC1091 $(notdir $(wildcard infra/vultr/*.sh)) moody-cli
	docker run --rm -e MOODY_PUBLIC_HOST=moody.example -v "$(CURDIR)/infra/vultr/config/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

release-check: ## Show what REF= would ship and what is live now (read-only; deploys nothing)
	infra/vultr/release.sh "$(REF)" --dry-run

release: ## Deploy the commit REF= to the public site, after a typed confirmation, then check it
	infra/vultr/release.sh "$(REF)"

vultr-plan: ## Show the reviewed plan at live list prices (public API; no key; creates nothing)
	infra/vultr/provision.sh plan

test-hosted: ## Playwright against a running deployment: MOODY_HOSTED_URL=, MOODY_HOSTED_TARGET=vultr|local-tls-proxy
	$(PNPM) --dir $(FE) exec playwright test --config playwright.hosted.config.ts

sandbox-clean: ## Force-remove any leftover sandbox containers
	@ids=$$(docker ps -aq --filter label=io.moody-blues.sandbox); \
	if [ -n "$$ids" ]; then docker rm -f $$ids; else echo "no sandbox containers"; fi

clean: ## Remove caches and build output (literal paths only)
	rm -rf .pytest_cache .ruff_cache frontend/.next frontend/.next-lab frontend/playwright-report frontend/test-results frontend/test-results-design frontend/.e2e-design
