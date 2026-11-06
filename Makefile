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
        test-hosted release release-check external-preflight external-run external-investigate external-demo \
        external-test external-containment external-bench external-eval external-investigator-eval external-ui \
        worlds-ui worlds-demo \
        local-preflight local-smoke local-eval local-ui

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
	$(UV) run ruff format --check backend tests sdk examples
	$(UV) run ruff check backend tests sdk examples
	$(PNPM) --dir $(FE) lint

format: ## Auto-format and auto-fix Python
	$(UV) run ruff format backend tests sdk examples
	$(UV) run ruff check --fix backend tests sdk examples

typecheck: ## Pyright (strict) + tsc
	$(UV) run pyright
	$(PNPM) --dir $(FE) typecheck

test: ## Unit + World + Target Agent + experiment + Investigator + evaluation + explorer tests (offline; no network)
	$(PYTEST) tests/unit tests/world tests/agent tests/experiment tests/investigator tests/evaluation tests/explorer tests/external

test-integration: ## Docker sandbox integration + containment tests (needs a Docker daemon)
	$(PYTEST) tests/integration tests/security -m docker

external-preflight: ## Check an external agent's manifest and handshake in the real sandbox (MANIFEST=path)
	$(UV) run moody-blues external-preflight --manifest $(MANIFEST)

external-run: ## Run an external agent through a rehearsal investigation (MANIFEST=path; free unless LIVE=1 CONFIRM=1 SPEND=usd. LOCAL=1 uses Ollama, FAULT=none|phantom_failure|phantom_success)
	$(UV) run moody-blues external-run --manifest $(MANIFEST) $(if $(WORLD),--world $(WORLD)) \
		$(if $(LIVE),--live-inference) $(if $(CONFIRM),--confirm-billable) $(if $(SPEND),--approved-spend-usd $(SPEND)) \
		$(if $(LOCAL),--local-inference) $(if $(FAULT),--fault $(FAULT))

external-investigate: ## The real Investigator workflow against one target (TARGET=external_scripted|external_llm|internal_llm MANIFEST=path WORLD=name). Free: models are labeled fixtures, or local with LOCAL=1 LOCAL_INVESTIGATOR=1
	$(UV) run moody-blues external-investigate --target $(TARGET) $(if $(MANIFEST),--manifest $(MANIFEST)) \
		$(if $(WORLD),--world $(WORLD)) $(if $(LIVE),--live-inference) $(if $(LIVE_INVESTIGATOR),--live-investigator) \
		$(if $(CONFIRM),--confirm-billable) $(if $(SPEND),--approved-spend-usd $(SPEND)) \
		$(if $(LOCAL),--local-inference) $(if $(LOCAL_INVESTIGATOR),--local-investigator)

local-preflight: ## What Ollama has installed, and whether the selected model can be used. Generates nothing
	$(UV) run moody-blues local-preflight

local-eval: ## REAL local model: KITE scenarios and two investigations, checked from the evidence (MANIFEST=path OUT=dir). Free; no provider is paid
	$(UV) run python -m tests.external.evaluate_local --manifest $(MANIFEST) $(if $(OUT),--out $(OUT))

local-ui: ## The pages against real local evidence, in a real browser (MOODY_E2E_LOCAL_ARTIFACTS=dir). Starts no model
	cd $(FE) && $(PNPM) design:build && $(PNPM) exec playwright test --config playwright.local.config.ts

local-smoke: ## local-preflight, then one real generation on this machine. Free; no provider is paid
	$(UV) run moody-blues local-preflight --smoke

external-demo: ## Run both example agents through the real sandbox and Oracle. Scripts, not models; free
	$(UV) run moody-blues external-demo

external-test: ## External agent adapter tests over a real process boundary (offline; no Docker)
	$(PYTEST) tests/external

external-containment: ## External agent tests in the real sandbox (needs a Docker daemon)
	$(PYTEST) tests/integration/test_external_agent.py tests/integration/test_external_investigator.py tests/security/test_external_agent_containment.py -m docker

external-ui: ## External runs through the real pages, in a real browser. MOODY_E2E_EXTERNAL_DOCKER=1 uses real containers
	cd $(FE) && $(PNPM) design:build && $(PNPM) exec playwright test --config playwright.external.config.ts

worlds-ui: ## Both worlds through the real pages, in a real browser. MOODY_E2E_EXTERNAL_DOCKER=1 uses real containers
	cd $(FE) && $(PNPM) design:build && $(PNPM) exec playwright test --config playwright.worlds.config.ts

worlds-demo: ## The four Job Queue cases and the CRM, through one coordinator, in the real sandbox. Scripts, not models; free
	$(UV) run python -m tests.external.evaluate_worlds $(if $(OUT),--out $(OUT))

external-eval: ## The 16 adapter scenarios and their metrics, in the real sandbox. Scripts, not models; free
	$(UV) run python -m tests.external.evaluate

external-investigator-eval: ## Sprint 16 cases and boundaries in the real sandbox. Models are labeled fixtures; free
	$(UV) run python -m tests.external.evaluate_investigator

external-bench: ## Measure adapter startup, per-call overhead, memory and cleanup in the real sandbox
	$(UV) run python -m tests.external.bench

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

bench-freeze: ## Freeze a benchmark revision once, from the running local model (REVISION=, REASON=; free)
	$(UV) run moody-blues bench-freeze --revision $(or $(REVISION),1) $(if $(REASON),--reason "$(REASON)")

bench-verify: ## Check the frozen benchmark is committed and still matches the code (free)
	$(UV) run moody-blues bench-verify

bench-run: ## REAL local model: one benchmark stage (STAGE=pilot|main|sweep, MOODY_ARTIFACTS_DIR=dir). Free; no provider is paid
	$(UV) run moody-blues bench-run --stage $(STAGE) $(if $(LIMIT),--limit $(LIMIT))

bench-repro: ## Rerun each verified failure, with a no-fault control, in fresh worlds (MOODY_ARTIFACTS_DIR=dir; free)
	$(UV) run moody-blues bench-repro

bench-report: ## Recompute the benchmark from raw evidence (MOODY_ARTIFACTS_DIR=dir OUT=dir; free)
	$(UV) run moody-blues bench-report --out $(or $(OUT),docs/evaluations/sprint-19/results)

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
