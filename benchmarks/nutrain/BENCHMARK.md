# nutrain Behavioral Benchmark

An adversarial multiple-choice benchmark that tests whether a model understands the *non-obvious* behavioral edge cases of the [nutrain](https://github.com/PrimeIntellect-ai/NuTrain) training framework.

## What this tests

Each question shows a TRUE rule about nutrain behavior and a confirming code snippet, then asks: "what does this *different* snippet actually print?" The alternative snippet looks like the rule should apply, but doesn't — the model must notice the subtle difference.

Questions require understanding of:
- PyTorch dtype propagation (RMSNorm, bfloat16 paths, float32 upcasting)
- AdaLayerNorm modulation (lipschitz path, zero-init, scale/shift normalization)
- Muon optimizer exclusion rules (`is_muon_updated`, name-substring matching)
- Expert router gating (capacity computation, renormalization, num_tokens semantics)
- RectifiedFlowLoss weighting (min-SNR-5, cosine median sampling)
- SwiGLU expert initialization (fan-in scaling, offset computation)
- FSDP2 wrapping heuristics (`would_wrap` size thresholds)

## Dataset

| File | Count | Notes |
|------|-------|-------|
| `environments/benchmark_mc/benchmark_mc/data/nutrain.jsonl` | 58 | Active eval set |
| `environments/benchmark_mc/benchmark_mc/data/all.jsonl` | 78 | All benchmarks combined |

Each JSONL record:
```json
{
  "id": "adv_rmsnorm__rmsnorm_with_elementwise_affin_4bf636de",
  "family": "rmsnorm_dtype_chain",
  "difficulty": 3,
  "is_hard_negative": false,
  "question": "...",
  "correct_id": "B",
  "explanation": "...",
  "source_benchmark": "nutrain"
}
```

## Eval results (58 questions)

| Model | pass@1 | pass@2 | Notes |
|-------|--------|--------|-------|
| `qwen/qwen3-8b` | **81%** | 83% | Baseline target model |
| `deepseek/deepseek-r1-0528` | 67% | 83% | Strong pass@2 but inconsistent |
| `arcee-ai/trinity-mini` | (pending) | — | — |

Run an eval yourself:
```bash
vf-eval benchmark_mc.benchmark_mc \
  -m qwen/qwen3-8b \
  --provider prime \
  --env-args '{"library": "nutrain"}' \
  --num-examples 58
```

## Generation pipeline

Questions are generated with the 3-player SGS (Self-Generated Specialization) adversarial game:

1. **Player 1 (Proposer)** — writes a TRUE behavioral rule + confirming snippet
2. **Player 2 (Adversary)** — finds a confounder where the rule breaks; must require two reasoning hops
3. **Guide LLM** — scores quality on 4 axes; rejects until all pass threshold

### Reproducing generation

```bash
cd benchmark-creator/

# Generate harder questions (uses qwen3-max as adversary)
python3 -m benchmark_creator \
  --families benchmarks/nutrain/meta/repo_profile.json \
  --strategy sgs \
  --model qwen/qwen3-max \
  --provider prime \
  --python-bin "uv run --with torch --with 'numpy<2' python3" \
  --n 3

# Merge into nutrain.jsonl + all.jsonl (run after generation)
python3 scripts/merge_benchmark.py \
  --source benchmarks/nutrain/tasks/ \
  --nutrain environments/benchmark_mc/benchmark_mc/data/nutrain.jsonl \
  --all environments/benchmark_mc/benchmark_mc/data/all.jsonl
```

Key generation config (in `scripts/generators/adversarial_mc.py`):

| Parameter | Value | Why |
|-----------|-------|-----|
| `MIN_NON_TRIVIAL` | 4 | Confounding mechanism must be hard to spot |
| `MIN_TWO_STEP` | 3 | Confounder must require two independent reasoning hops |
| `max_guide_retries` | 5 | More attempts before giving up on a P1 rule |
| P2 model | `qwen/qwen3-max` | qwen3-8b as P2 was too weak — confounders were obvious |

### Preamble system

Each family has a `preamble` in `benchmarks/nutrain/meta/repo_profile.json` — minimal class/function definitions injected into both player prompts and prepended to executed snippets. This is necessary because:
- macOS Intel only has PyTorch 2.2.x (`torch.nn.RMSNorm` requires 2.4+)
- Questions must be self-contained (no external imports beyond torch/math)

### Python runtime for snippet verification

Snippets use `uv run --with torch --with 'numpy<2' python3` because torch 2.2.x was compiled against NumPy 1.x. Running with NumPy 2.x causes an import error.

## Families

| Family ID | What it tests |
|-----------|---------------|
| `rmsnorm_dtype_chain` | bfloat16 vs float32 propagation through RMSNorm affine/non-affine paths |
| `adaln_continuous_lipschitz` | AdaLayerNormContinuous lipschitz path — rms_norm on scale/shift breaks identity |
| `adaln_zero_modulation` | AdaLayerNormZero — norm_layer applies to x, not to (scale, shift) |
| `muon_optimizer_mesh` | `is_muon_updated` substring matching — `proj_out` vs `output_proj` |
| `expert_router_gating` | ExpertChoiceRouter capacity and renormalization edge cases |
| `rectified_flow_loss_weighting` | min-SNR-5 weight saturation; cosine median sampling |
| `swiglu_experts_init` | SwiGLU fan-in scaling and offset initialization |
| `fsdp2_wrapping` | `would_wrap` size threshold behavior |

## Saturation signal

When pass@1 > 90% for a model, add more SGS-round questions with stricter criteria:
- Increase `MIN_NON_TRIVIAL` to 5
- Increase `MIN_TWO_STEP` to 4
- Use `EvolInstructStrategy` to mutate existing questions (param_shift, context_embed)
