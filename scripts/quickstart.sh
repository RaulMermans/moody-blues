#!/usr/bin/env bash
# The first reliability test: two scripted example agents, the same fault, real sandboxes and a real
# Oracle. No model, no credentials, no cost. Results stay in .moody-local until `make clean-local`.
set -euo pipefail
cd "$(dirname "$0")/.."

scripts/check-prereqs.sh >/dev/null || {
  echo "Prerequisites are missing. Run: scripts/check-prereqs.sh" >&2
  exit 2
}
eval "$(scripts/local-env.sh)"
case "$(basename "${MOODY_ARTIFACTS_DIR:-.artifacts}")" in
  .artifacts)
    echo "Refusing to write a demonstration into .artifacts. Unset MOODY_ARTIFACTS_DIR." >&2
    exit 2
    ;;
esac
export MOODY_LOG_LEVEL=WARNING

examples=examples/external-agent
echo "== 1 of 3: an agent that checks before it retries"
uv run moody-blues external-run --manifest "$examples/careful.agent.toml"
echo
echo "== 2 of 3: an agent that retries blindly, under the same fault"
uv run moody-blues external-run --manifest "$examples/unsafe.agent.toml"
echo
echo "== 3 of 3: check the evidence those runs wrote"
uv run moody-blues evidence-verify --dir "$MOODY_ARTIFACTS_DIR"
echo
echo "Both agents are scripts, not models: this shows the test bench, not how any LLM behaves."
echo "See the results in the browser:  make dev, then open http://127.0.0.1:3000/operator"
echo "Remove everything this wrote:    make clean-local"
