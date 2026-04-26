# CLAUDE_PRIMEINTELLECT.md

Guide for working with Prime Intellect (PI) environments in this repo.
Reference this file when: creating/updating PI environments, running RL training, evaluating models on PI infrastructure.

---

## Setup checklist

```bash
# 1. Install CLI (if missing)
uv tool install -U prime

# 2. Authenticate (one-time; opens browser)
prime login
# Verify: prime config view  (should show User ID and API Key)

# 3. Check SSH key for GPU pods
prime config set-ssh-key-path   # point to ~/.ssh/id_rsa or similar

# 4. Verify environment deps
cd environments/benchmark_mc
pip install -e .                # or: uv pip install -e .
```

---

## Repository structure

```
environments/
  benchmark_mc/             ← PI environment (pip-installable Python package)
    benchmark_mc.py         ← load_environment() entry point
    data/
      pandas_understanding.jsonl    ← bundled benchmark data
      scikit_learn.jsonl
      all.jsonl
    pyproject.toml
    README.md
scripts/
  bundle_pi_data.py         ← regenerate data/ from benchmarks/ directories
```

---

## Regenerating bundled data

Run this any time you add new benchmark questions:

```bash
python3 scripts/bundle_pi_data.py
# → environments/benchmark_mc/data/all.jsonl (20 tasks: 10 pandas + 10 scikit_learn)

# Add more benchmarks:
python3 scripts/bundle_pi_data.py --benchmarks pandas_understanding scikit_learn scrapy_50
```

---

## Evaluating a model locally

```bash
cd environments/benchmark_mc
pip install -e .

# Evaluate against OpenAI-compatible endpoint
prime eval run benchmark_mc -m openai/gpt-4.1-mini -n 20

# Target one library
prime eval run benchmark_mc \
  -m openai/gpt-4.1-mini \
  --env-args '{"library": "pandas"}' \
  -n 10

# Launch TUI to inspect rollouts
prime eval tui
```

---

## Pushing environment to PI Hub

```bash
prime env push                              # Public (under your username)
prime env push --visibility=PRIVATE         # Private
prime env push --auto-bump                  # Auto-increment version

# Others can then install with:
prime env install <your-username>/benchmark-mc
```

---

## RL training — hill climbing strategy

**Goal**: fine-tune a small model (≤3B) to beat larger models on library-specific behavioral questions.

### Recommended model for hill climbing with $200 PI credits

- **Qwen2.5-1.5B-Instruct** or **Qwen3-1.7B** — fast, cheap to run, known to respond well to RL
- Baseline accuracy on benchmark-mc: ~40-50% (random = 25%, GPT-4o = ~75%)
- Target: 65%+ after RL fine-tuning on 20 questions × 3 rollouts

### Hosted training (simplest path)

```bash
# Get example configs
prime lab setup

# Run RL training via PI managed infrastructure
# Edit configs/hosted_training.toml first (set model, env, hyperparams)
prime lab train --config configs/hosted_training.toml
```

### prime-rl (for more control)

```bash
prime lab setup --prime-rl
# Follow prime-rl docs; environment is passed as:
#   env_name = "benchmark_mc"
#   env_args = {"library": "all", "chain_of_thought": true}
```

### On-demand GPU pod (manual RL)

```bash
# Check available GPUs
prime availability list --gpu-type H100_80GB

# Launch a pod
prime pods create

# SSH in
prime pods ssh <pod-id>

# Inside pod:
pip install prime verifiers datasets trl
python3 -c "
from benchmark_mc.benchmark_mc import load_environment
env = load_environment(library='all', chain_of_thought=True, format_reward_weight=0.2)
# Wire into your RL trainer (TRL GRPOTrainer, SkyRL, etc.)
"
```

---

## Environment API reference

```python
from benchmark_mc.benchmark_mc import load_environment

env = load_environment(
    library="all",            # "pandas" | "scikit_learn" | "all"
    max_examples=None,        # cap dataset size
    chain_of_thought=True,    # append CoT instruction to user prompt
    format_reward_weight=0.0, # 0.2 to bootstrap early RL, then anneal to 0
)

# env is a vf.SingleTurnEnv
# reward: 1.0 correct, 0.0 wrong, parses last A/B/C/D from response
```

---

## Training tips

1. **Baseline first**: run `prime eval run` before training; record accuracy per family
2. **If baseline < 10%**: model can't read the question — check chat template (Qwen3/DeepSeek-R1 need special handling)
3. **Format reward**: set `format_reward_weight=0.2` for first 50 steps if model abstains a lot; anneal to 0
4. **Families to focus on**: `copy_semantics` and `nan_semantics` are hardest (most models get <40%)
5. **Overfitting risk**: 20 questions is small — use held-out evaluation; generate more questions with `benchmark_creator` + `bundle_pi_data.py` before training

---

## Adding more questions (expand the training set)

```bash
# Generate 10 more scikit-learn questions
ANTHROPIC_API_KEY=sk-ant-... python3 -m benchmark_creator \
  --repo https://github.com/scikit-learn/scikit-learn \
  --strategy sgs --n 3 --max-tasks 10 \
  --output benchmarks/scikit_learn_v2

# Re-bundle
python3 scripts/bundle_pi_data.py --benchmarks \
  pandas_understanding scikit_learn scikit_learn_v2

# Bump and push
cd environments/benchmark_mc
prime env push --auto-bump
```

---

## Measuring improvement

After training, evaluate the fine-tuned checkpoint via PI inference:

```bash
prime eval run benchmark_mc \
  -m openai/<your-finetuned-model-endpoint> \
  --env-args '{"library": "all"}' \
  -n 20 --rollouts-per-example 3 \
  --save-results results/finetuned_eval.json

# Compare against baseline
python3 -c "
import json
base = json.load(open('results/baseline_eval.json'))
ft   = json.load(open('results/finetuned_eval.json'))
print('Baseline accuracy:', sum(r['reward']==1.0 for r in base)/len(base))
print('Fine-tuned accuracy:', sum(r['reward']==1.0 for r in ft)/len(ft))
"
```
