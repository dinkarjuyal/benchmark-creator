#!/usr/bin/env bash
# Run the full Scrapy-50 benchmark with one or more agents.
# Usage:
#   ./scripts/run_benchmark.sh haiku          # haiku only (cheapest, ~$1-2)
#   ./scripts/run_benchmark.sh haiku sonnet   # haiku + sonnet
#   ./scripts/run_benchmark.sh all            # all three configured agents
#
# Results land in results/runs/<task_id>/<run_dir>/
# Analyze with: python3 scripts/analyze_results.py
#
# Requires: ANTHROPIC_API_KEY set in environment, Docker running.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

BENCHMARK="scrapy_50"
PARALLELISM=4   # run 4 tasks at once; raise to 8 if machine has headroom

declare -A AGENT_MAP
AGENT_MAP[haiku]="mini_claude_haiku_4_5"
AGENT_MAP[sonnet]="mini_claude_sonnet_4_6"
AGENT_MAP[opus]="mini_claude_opus_4_6"

AGENTS=()
if [[ $# -eq 0 || "$1" == "all" ]]; then
    AGENTS=("mini_claude_haiku_4_5" "mini_claude_sonnet_4_6" "mini_claude_opus_4_6")
else
    for arg in "$@"; do
        key="${arg,,}"
        if [[ -n "${AGENT_MAP[$key]+x}" ]]; then
            AGENTS+=("${AGENT_MAP[$key]}")
        else
            echo "Unknown agent shorthand: $arg (valid: haiku, sonnet, opus, all)"
            exit 1
        fi
    done
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "ERROR: ANTHROPIC_API_KEY is not set."
    exit 1
fi

echo "Running benchmark '$BENCHMARK' with agents: ${AGENTS[*]}"
echo "Parallelism: $PARALLELISM"
echo ""

for AGENT in "${AGENTS[@]}"; do
    echo "===== Agent: $AGENT ====="
    python3 -m harness.run_tasks \
        --benchmark "$BENCHMARK" \
        --agent "$AGENT" \
        --allow-agent-network \
        --n-parallel "$PARALLELISM" \
        --results-dir results/runs
    echo ""
done

echo "All runs complete. Analyze with:"
echo "  python3 scripts/analyze_results.py"
