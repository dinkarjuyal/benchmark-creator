# CDBench Runbook

All commands to run evaluation and RL training. Copy-paste ready.

## End-to-end pipeline (sklearn, GPU-only, 24-hour window)

```
Step 0  Install deps + download model    (~10 min)
Step 1  Generate SGS corruptions         (~1h,  4×H100, 32B model)
Step 2  Discover T_fail                  (~3h,  CPU, pytest)
Step 3  Baseline eval of small model     (~30m, 1×H100, 1.5B model)
Step 4  RL training (GRPO)               (~8h,  1×H100, 1.5B + LoRA)
Step 5  Post-RL eval + compare           (~30m, 1×H100)
```

Steps 2 and 3 can run in parallel (different terminals).

---

## Infrastructure

| Item | Value |
|------|-------|
| H100 server | `ubuntu@34.86.165.36` |
| SSH key | `~/.ssh/nodeset3_ed25519` |
| Repo on server | `~/cdbench/repo/` |
| Conda env | `cdbench` |
| HF cache | `/mnt/localssd/cdbench/hf_cache` |
| Sandboxes | `/mnt/localssd/cdbench/sandboxes/{sklearn,fastapi}/` |
| T_fail cache | `/mnt/localssd/cdbench/tfail_cache/` (sklearn) |
| | `/mnt/localssd/cdbench/tfail_cache_fastapi/` (fastapi) |
| Results | `~/cdbench/repo/results/local_eval/` |

---

---

## Step 0: Install dependencies + download small model

Run once on the server:

```bash
 export PATH=$HOME/miniconda3/bin:$PATH
 source $HOME/miniconda3/etc/profile.d/conda.sh
 export HF_HOME=/mnt/localssd/cdbench/hf_cache
 conda activate cdbench

# RL training dependencies
  pip install "trl>=0.12" peft accelerate
  
# Download Qwen2.5-Coder-1.5B (the RL training target)
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('Qwen/Qwen2.5-Coder-1.5B-Instruct',
                  cache_dir='/mnt/localssd/cdbench/hf_cache')
print('Done')
"
```

---

## Connect to the Server

**From your terminal (Mac):**

```bash
ssh -i ~/.ssh/nodeset3_ed25519 ubuntu@34.86.165.36
```

**Use tmux so jobs survive if your terminal disconnects** (critical for 8-hour training runs):

```bash
# On server: start a named session
tmux new -s cdbench

# Detach without killing the job: Ctrl+B, then D
# Re-attach later from any terminal:
tmux attach -t cdbench

# List running sessions:
tmux ls

# Open a second pane (split horizontally) to monitor while training runs:
# Ctrl+B, then "  (double-quote)
# Switch between panes: Ctrl+B, then arrow key
```

**Activate the conda environment** (do this in every new shell/pane):

```bash
export PATH=$HOME/miniconda3/bin:$PATH
source $HOME/miniconda3/etc/profile.d/conda.sh
export HF_HOME=/mnt/localssd/cdbench/hf_cache
conda activate cdbench
cd ~/cdbench/repo
```

---

## Sync Local Code to Server

Run from your **local machine** to push the latest repo state to the server:

```bash
rsync -avz --exclude='*.pyc' --exclude='__pycache__' --exclude='results/' \
  -e "ssh -i ~/.ssh/nodeset3_ed25519" \
  /Users/dinkarjuyal/Desktop/agents/benchmark-creator/ \
  ubuntu@34.86.165.36:~/cdbench/repo/
```

To also sync results back from server to local:

```bash
rsync -avz \
  -e "ssh -i ~/.ssh/nodeset3_ed25519" \
  ubuntu@34.86.165.36:~/cdbench/repo/results/ \
  /Users/dinkarjuyal/Desktop/agents/benchmark-creator/results/
```

---

## Part 1: T_fail Discovery (one-time setup)

T_fail = which tests flip pass→fail for each corruption. Must be run once per sandbox before evaluation.

### sklearn (already done — 16/20 healthy)

Status from `results/tfail_summary_sklearn_hand.json`:
- **NO_TFAIL** (skip in eval): `hc_02`, `hc_07`, `hc_13`, `hc_18`
- **HEALTHY** (16 corruptions): all others

To re-run (e.g., after adding new corruptions):

```bash
# On server, in conda env
cd ~/cdbench/repo
python scripts/discover_tfail.py --domain sklearn --catalog hand
# Output: results/tfail_summary_sklearn_hand.json
# Cache: /mnt/localssd/cdbench/tfail_cache/
```

To re-run only the NO_TFAIL ones with the full test suite:

```bash
python scripts/discover_tfail.py --domain sklearn --catalog hand --refresh-zero --full-suite
```

### FastAPI (needs full-suite re-run to populate individual cache files)

The narrow test mapping only cached fa_01–fa_07. The full-suite run (stored in `tfail_summary_fastapi_unhealthy_full.json`) shows 19/20 healthy, but the individual cache files for fa_09–fa_20 are missing. Also, the FastAPI sandbox is missing `.cdbench_ready` — `discover_tfail.py` will pip-install and fix this automatically.

```bash
cd ~/cdbench/repo
# This re-pips the sandbox, touches .cdbench_ready, and writes all 20 cache files
python scripts/discover_tfail.py --domain fastapi --catalog hand --full-suite --refresh
# Output: results/tfail_summary_fastapi_hand.json
# Cache files: /mnt/localssd/cdbench/tfail_cache_fastapi/fa_01_*.json ... fa_20_*.json
# Expected: 19/20 healthy (fa_08 still 0 — needs replacement corruption)
```

---

## Step 1: Generate SGS Corruptions (programmatic, GPU-powered)

Uses Qwen2.5-Coder-32B as the Proposer + Guide. Generates subtle, test-verified
single-point bugs across all 6 sklearn source files. No handcrafting.

```bash
cd ~/cdbench/repo

# Generate 30 proposals per source file (6 files × 30 = 180 proposals)
# After Guide filtering (~50% accept rate): ~90-100 corruptions
# Runtime: ~45-60 minutes on 4×H100 with 32B model
python scripts/generate_sgs_vllm.py \
    --model Qwen/Qwen2.5-Coder-32B-Instruct \
    --tp 4 \
    --n-per-file 30 \
    --domain sklearn \
    --out results/sgs_corruptions_sklearn.json

# Output: results/sgs_corruptions_sklearn.json
# Check how many were accepted:
python3 -c "import json; d=json.load(open('results/sgs_corruptions_sklearn.json')); print(len(d),'corruptions')"
```

To generate more (second pass, appended):

```bash
python scripts/generate_sgs_vllm.py \
    --model Qwen/Qwen2.5-Coder-32B-Instruct \
    --tp 4 \
    --n-per-file 20 \
    --domain sklearn \
    --out results/sgs_corruptions_sklearn.json \
    --append
```

## Step 2: Discover T_fail for SGS Corruptions

Runs pytest to find which tests flip pass→fail per corruption.
CPU-bound — can run in parallel with Step 3 in a second terminal.

```bash
cd ~/cdbench/repo

python scripts/discover_tfail.py --domain sklearn --catalog sgs
# Runtime: ~2-4 hours (each corruption = 2 pytest runs on sklearn tests)
# Output: results/tfail_summary_sklearn_sgs.json
# Cache:  /mnt/localssd/cdbench/tfail_cache/

# Check how many are testable:
python3 -c "
import json
d = json.load(open('results/tfail_summary_sklearn_sgs.json'))
healthy = [c for c in d['corruptions'] if len(c.get('tfail',[])) > 0]
print(f'{len(healthy)}/{len(d[\"corruptions\"])} healthy SGS corruptions')
"
```

## Step 3: Baseline Eval of Small Model (run in parallel with Step 2)

Establishes the pre-RL baseline. Shows where the 1.5B model currently stands.

```bash
cd ~/cdbench/repo

# After Step 2 completes, or run with --catalog hand in the meantime
python scripts/run_eval_local.py \
    --model Qwen/Qwen2.5-Coder-1.5B-Instruct \
    --domain sklearn \
    --catalog sgs \
    --tp 1 \
    --max_tokens 4096 \
    --max_model_len 8192 \
    --counts 1,3,5 \
    --diversity clustered,scattered \
    --trials 3

# Output: results/local_eval/Qwen_Qwen2.5-Coder-1.5B-Instruct_domain=sklearn_cat=sgs_n=1_3_5_...json
```

## Step 4: RL Training (GRPO)

Trains the 1.5B model with functional rewards. Trains on n=1 (single bug) for clean signal.

```bash
cd ~/cdbench/repo

python scripts/train_rl.py \
    --model Qwen/Qwen2.5-Coder-1.5B-Instruct \
    --domain sklearn \
    --catalog sgs \
    --train-ns "1:0.6,3:0.3,5:0.1" \
    --steps 200 \
    --G 8 \
    --lr 1e-5 \
    --lora-rank 16 \
    --total-examples 400 \
    --eval-interval 20 \
    --out checkpoints/rl_1.5b_sklearn_sgs

# --train-ns "1:0.6,3:0.3,5:0.1" = curriculum:
#   60% single-bug (strong reward signal to bootstrap learning)
#   30% three-bug  (teaches multi-bug reasoning)
#   10% five-bug   (harder generalization target)
#
# Runtime: ~6-10 hours (200 steps × ~2-3min/step for 8 rollouts + pytest scoring)
# Checkpoints: checkpoints/rl_1.5b_sklearn_sgs/  (saved every 20 steps)
# Merged model: checkpoints/rl_1.5b_sklearn_sgs/merged/
```

To monitor training loss live:

```bash
tail -f checkpoints/rl_1.5b_sklearn_sgs/trainer_log.jsonl 2>/dev/null || \
  watch -n5 "ls -lt checkpoints/rl_1.5b_sklearn_sgs/ | head -5"
```

## Step 5: Post-RL Eval + Comparison

```bash
cd ~/cdbench/repo

# Eval post-RL model
python scripts/run_eval_local.py \
    --model checkpoints/rl_1.5b_sklearn_sgs/merged \
    --domain sklearn \
    --catalog sgs \
    --tp 1 \
    --max_tokens 4096 \
    --max_model_len 8192 \
    --counts 1,3,5 \
    --diversity clustered,scattered \
    --trials 3

# Compare pre vs post RL
python3 << 'EOF'
import json, glob
from pathlib import Path

files = sorted(Path("results/local_eval").glob("*1.5B*_cat=sgs*n=1_3_5*.json"))
for f in files:
    d = json.load(open(f))
    results = d.get("results", [])
    by_n = {}
    for r in results:
        by_n.setdefault(r["n"], []).append(r.get("functional", {}).get("score", 0))
    label = "POST-RL" if "merged" in str(f) or "rl_" in str(f) else "PRE-RL"
    print(f"\n{label} ({f.name[:60]})")
    for n, scores in sorted(by_n.items()):
        print(f"  n={n}: {sum(scores)/len(scores):.0%} (n={len(scores)} runs)")
EOF
```

---

## Part 2: Local vLLM Evaluation (H100)

### Pre-downloaded models

| Model | Tensor Parallel | Best for |
|-------|----------------|----------|
| `Qwen/Qwen2.5-Coder-7B-Instruct` | `--tp 2` | Quick runs (cheaper) |
| `Qwen/Qwen2.5-Coder-32B-Instruct` | `--tp 4` | High-quality results |

### Using the wrapper script (`run_eval.sh`)

```bash
# run_eval.sh <label> <model> <tp> <counts> [domain] [max_tokens]
# domain defaults to sklearn, max_tokens defaults to 16384

# sklearn — full difficulty axis
bash run_eval.sh "7b_sklearn" \
  "Qwen/Qwen2.5-Coder-7B-Instruct" 2 "1,3,5,7,10,15,20" sklearn

bash run_eval.sh "32b_sklearn" \
  "Qwen/Qwen2.5-Coder-32B-Instruct" 4 "1,3,5,7,10,15,20" sklearn

# fastapi — run T_fail discovery first (see Part 1)
bash run_eval.sh "7b_fastapi" \
  "Qwen/Qwen2.5-Coder-7B-Instruct" 2 "1,3,5,7,10" fastapi

bash run_eval.sh "32b_fastapi" \
  "Qwen/Qwen2.5-Coder-32B-Instruct" 4 "1,3,5,7,10" fastapi
```

### Direct script (more control)

```bash
cd ~/cdbench/repo

# sklearn — 7B, full axis
python scripts/run_eval_local.py \
  --model Qwen/Qwen2.5-Coder-7B-Instruct \
  --domain sklearn \
  --tp 2 \
  --max_tokens 8192 \
  --max_model_len 16384 \
  --counts 1,3,5,7,10,15,20 \
  --diversity clustered,scattered \
  --trials 3

# sklearn — 32B, full axis (TP=4, needs ~4×H100)
python scripts/run_eval_local.py \
  --model Qwen/Qwen2.5-Coder-32B-Instruct \
  --domain sklearn \
  --tp 4 \
  --max_tokens 16384 \
  --max_model_len 32768 \
  --counts 1,3,5,7,10,15,20 \
  --diversity clustered,scattered \
  --trials 3

# sklearn — 32B, extend (just n=20, missing from current data)
python scripts/run_eval_local.py \
  --model Qwen/Qwen2.5-Coder-32B-Instruct \
  --domain sklearn \
  --tp 4 \
  --max_tokens 16384 \
  --max_model_len 32768 \
  --counts 20 \
  --diversity clustered,scattered \
  --trials 3

# fastapi — 7B (run T_fail discovery first)
python scripts/run_eval_local.py \
  --model Qwen/Qwen2.5-Coder-7B-Instruct \
  --domain fastapi \
  --tp 2 \
  --max_tokens 8192 \
  --max_model_len 16384 \
  --counts 1,3,5,7,10 \
  --diversity clustered,scattered \
  --trials 3

# fastapi — 32B
python scripts/run_eval_local.py \
  --model Qwen/Qwen2.5-Coder-32B-Instruct \
  --domain fastapi \
  --tp 4 \
  --max_tokens 16384 \
  --max_model_len 32768 \
  --counts 1,3,5,7,10 \
  --diversity clustered,scattered \
  --trials 3
```

> **Output**: `results/local_eval/<model>_domain=<domain>_n=<counts>_d=<diversity>_t<trials>.json`

> **Healthy corruptions**: sklearn 16/20, fastapi 14/20 (from existing cache). Run T_fail discovery to get fastapi to 19/20.

### Download a new model for evaluation

```bash
python -c "
from huggingface_hub import snapshot_download
snapshot_download('Qwen/Qwen2.5-Coder-14B-Instruct',
                  cache_dir='/mnt/localssd/cdbench/hf_cache')
"
```

---

## Part 3: API-based Ablation (from local machine or server)

Uses the Prime Intellect or OpenRouter API. Does NOT require GPUs.

### Environment variables

```bash
export PROVIDER=prime          # or: openrouter, anthropic
export PRIME_API_KEY=<key>     # Prime Intellect API key
# OR
export OPENROUTER_API_KEY=<key>
```

### Run ablation for one model

```bash
cd /Users/dinkarjuyal/Desktop/agents/benchmark-creator  # local

MODEL=deepseek/deepseek-r1-0528 \
MAX_TOKENS=32768 \
N_TRIALS=3 \
python scripts/benchmark_ablation.py
# Output: results/ablation_deepseek_deepseek-r1-0528.json

MODEL=qwen/qwen3-coder \
MAX_TOKENS=8192 \
python scripts/benchmark_ablation.py
# Output: results/ablation_qwen_qwen3-coder.json
```

### Run ablation for all 5 paper models

```bash
for MODEL in \
  "deepseek/deepseek-r1-0528" \
  "deepseek/deepseek-chat" \
  "qwen/qwen3-coder" \
  "qwen/qwen3-max" \
  "Qwen/Qwen3.5-2B"; do
  echo "=== $MODEL ==="
  MODEL="$MODEL" N_TRIALS=3 python scripts/benchmark_ablation.py
done
```

### Re-run only broken clustered conditions

```bash
MODEL=deepseek/deepseek-chat python scripts/rerun_clustered.py
```

### FastAPI ablation (API-based, text-match only)

Use this when you want to evaluate API models on FastAPI without a GPU. Text-match scoring only (no functional judge).

```bash
MODEL=qwen/qwen3-coder \
MAX_TOKENS=8192 \
DOMAIN=fastapi \
python scripts/benchmark_ablation.py
```

> For GPU-based FastAPI eval with functional scoring, use `run_eval_local.py --domain fastapi` (Part 2).

---

## Part 4: RL Hill Climbing (Prime Intellect)

Uses the `benchmark_mc` environment to fine-tune a small model on the MCQ benchmark.

### One-time auth (local machine only)

```bash
uv tool install -U prime  # install CLI if missing
prime login               # opens browser — do this once
prime config view         # verify: shows User ID + API Key
```

### Regenerate bundled benchmark data

Run this after adding new corruptions or benchmarks:

```bash
cd /Users/dinkarjuyal/Desktop/agents/benchmark-creator
python scripts/bundle_pi_data.py
# Output: environments/benchmark_mc/data/all.jsonl (20 tasks)

# Include scrapy_50 too:
python scripts/bundle_pi_data.py \
  --benchmarks pandas_understanding scikit_learn scrapy_50
```

### Push environment to PI Hub

```bash
cd environments/benchmark_mc
prime env push --auto-bump
# Others install with: prime env install <username>/benchmark-mc
```

### Evaluate baseline before training

```bash
prime eval run benchmark_mc \
  -m openai/gpt-4.1-mini \
  -n 20 \
  --save-results results/baseline_eval.json

# Save accuracy
python3 -c "
import json
d = json.load(open('results/baseline_eval.json'))
acc = sum(r['reward']==1.0 for r in d)/len(d)
print(f'Baseline: {acc:.0%} ({sum(r[\"reward\"]==1.0 for r in d)}/{len(d)})')
"
```

### Run RL training (hosted — simplest)

```bash
# Get starter config
prime lab setup

# Edit configs/hosted_training.toml:
#   model = "Qwen/Qwen2.5-1.5B-Instruct"
#   env_name = "benchmark_mc"
#   env_args = {library = "all", chain_of_thought = true, format_reward_weight = 0.2}

prime lab train --config configs/hosted_training.toml
```

### Evaluate fine-tuned model

```bash
prime eval run benchmark_mc \
  -m openai/<your-finetuned-endpoint> \
  --env-args '{"library": "all"}' \
  -n 20 --rollouts-per-example 3 \
  --save-results results/finetuned_eval.json

python3 -c "
import json
base = json.load(open('results/baseline_eval.json'))
ft   = json.load(open('results/finetuned_eval.json'))
print('Baseline:', f\"{sum(r['reward']==1.0 for r in base)/len(base):.0%}\")
print('Fine-tuned:', f\"{sum(r['reward']==1.0 for r in ft)/len(ft):.0%}\")
"
```

---

## Part 5: Results Analysis

### Aggregate and compare all models

```bash
python3 << 'EOF'
import json, glob
from pathlib import Path

root = Path("results")
for path in sorted(root.glob("local_eval/*.json")):
    d = json.load(open(path))
    runs = d.get("results", [])
    print(f"\n=== {d.get('model', path.name)} ===")
    by_n = {}
    for r in runs:
        key = (r["n"], r["diversity"])
        by_n.setdefault(key, []).append(r.get("functional", {}).get("score", 0))
    for (n, div), scores in sorted(by_n.items()):
        avg = sum(scores)/len(scores)
        print(f"  n={n:2d} {div:10s}  {avg:.0%}  ({scores})")
EOF
```

### Check what's already evaluated

```bash
ls results/local_eval/
ls results/ablation_*.json
```

---

## Known Gaps / TODOs

| Item | Status | Fix |
|------|--------|-----|
| FastAPI T_fail cache | 14/20 healthy from partial cache | `discover_tfail.py --domain fastapi --full-suite --refresh` → 19/20 |
| `fa_08` | 0 T_fail (untestable) | Replace the corruption or drop it |
| `hc_02,07,13,18` | 0 T_fail in sklearn | Auto-excluded from local eval; replace or drop for paper |
| DeepSeek R1 n=20 | 20 runs missing | Re-run via API with `MAX_TOKENS=32768` |
| 32B sklearn n=20 | Not yet run on H100 | `bash run_eval.sh "32b_n20" "Qwen/Qwen2.5-Coder-32B-Instruct" 4 "20" sklearn` |
