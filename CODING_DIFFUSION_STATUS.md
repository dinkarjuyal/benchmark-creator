# CODING DIFFUSION — STATUS & NEXT STEPS

## What's Built

Coding diffusion strategy for benchmark-creator: forward process corrupts clean code (adding "noise"/bugs), agent performs reverse process (denoising/debugging). Difficulty controlled by number of corruptions (noise schedule).

### Files

| File | Purpose |
|------|---------|
| `scripts/generators/coding_diffusion.py` | Main strategy: CorruptionSpec, DiffusionSchedule, CodingDiffusionGenerator, dual-path generation (patterns → LLM fallback) |
| `scripts/generators/bug_patterns.py` | 9 deterministic bug patterns (OffByOne, LogicalOperator, Indexing, NullCheck, ReturnValue, TypeCast, RangeLoop, Assertion, EarlyReturn) |
| `scripts/task_writer_diffusion.py` | Writes code-fixing tasks to disk (setup.py applies find/replace patches) |
| `scripts/verifier_builder_diffusion.py` | Generates validator scoring by test pass rate (0.5 visible + 0.3 hidden + 0.1 regression + 0.1 policy) |
| `scripts/benchmark_quick.py` | Lightweight PI benchmark: corrupts code → calls PI model → scores fix by running pytest |
| `scripts/benchmark_pi_diffusion.py` | Full PI benchmark with manual + pattern corruptions (heavier) |
| `benchmark_creator/cli.py` | 5 new CLI flags: --corruption-count, --corruption-spread, --corruption-dependency, --subtlety-min/max |
| `tests/test_coding_diffusion.py` | 37 tests covering all components |

### Branch

All changes on `feature/coding-diffusion-v2` (previously pushed to main as f7fca95).

## Benchmark Results (PI Models)

Tested on a hand-crafted `math_utils.py` with 8 functions and 5 simple single-line corruptions.

| Model | 1 bug | 2 bugs | 3 bugs | 4 bugs | 5 bugs |
|-------|-------|--------|--------|--------|--------|
| deepseek-chat | 1/1 | 2/2 | 3/3 | 3/4 | **3/5** |
| qwen3-coder | 1/1 | 2/2 | 3/3 | 2/4 | 4/5 |
| qwen3-8b | 1/1 | 1/2 | 3/3 | 3/4 | 4/5 |
| qwen3.5-2b | 0/1 | 0/2 | 2/3 | 3/4 | 2/5 |

**DeepSeek-Chat shows clearest scaling**: 100% → 75% → 60% bug fix rate. Weak models (2B) struggle even at 1 bug.

## Known Issues

1. **Benchmark too easy**: Hand-crafted math_utils.py with simple single-line bugs. 8B models can mostly handle 3-5 bugs. Need real repos with multi-file, cascading bugs.
2. **Pattern verification**: `_extract_test_calls()` auto-generates test calls args from function signatures, but many patterns produce bugs invisible to the auto-generated calls. Only ~2-3 patterns per code file pass verification.
3. **Test pass rate is misleading**: Some bugs don't affect test output (e.g., `if x < lo` → `if x > lo` in clamp returns same value at boundary). Bug fix rate is the better metric.
4. **No cascading/masking dependencies**: Current implementation supports `independent`, `cascading`, `masking` dependency types in DiffusionSchedule, but the composition logic doesn't actually implement cascading (where bug B hides bug A) or masking effects. Only independent corruptions work.
5. **PI API**: PIClientAdapter uses OpenAI-compatible endpoint at `https://api.pinference.ai/api/v1`. Key loaded via `verifiers.utils.client_utils.load_prime_config()`.

## Next Steps for Other Agents

### Priority 1: Test on real repos
- Use `RepoAnalyzer` (already in `adversarial_mc.py`) to clone and analyze real GitHub repos
- Apply corruptions to actual library source code (pandas, scikit-learn, numpy)
- This will naturally create harder, multi-file debugging tasks

### Priority 2: Implement cascading dependencies
- In `CodingDiffusionGenerator._compose_task()`, when `schedule.dependency == "cascading"`:
  - Bug B should be placed in a function that Bug A calls
  - Fixing Bug A first reveals that Bug B exists (the test still fails after fixing A)
- When `schedule.dependency == "masking"`:
  - Bug B's error output masks Bug A's error output
  - Agent must fix B first to even see that A exists

### Priority 3: Multi-file corruption
- Current corruptions are all in the same file
- Spread `scattered` should genuinely pick different files
- Add corruptions across src/, tests/, and config files

### Priority 4: Test at 7-10 corruption levels
- Current benchmark only goes to 5 bugs
- Need to find the "horizon limit" — the number of corruptions where even frontier models drop below 50% fix rate
- This is the key metric for "long horizon debugging"

### Priority 5: Compare with SWE-bench
- Calibrate difficulty: how many corruptions ≈ 1 SWE-bench issue?
- This gives a meaningful difficulty scale

## PI Models Available

Run `benchmark_quick.py` with any of these models:
```
qwen/qwen3-8b              # Fast, cheap, decent at simple bugs
qwen/qwen3-coder            # Very fast, code-specialized
deepseek/deepseek-chat       # Strongest scaling signal
Qwen/Qwen3.5-2B             # Weak baseline
qwen/qwen3-max              # Frontier — try this for harder tasks
deepseek/deepseek-r1-0528   # Reasoning model — should handle cascading bugs
```

## How to Run

```bash
# Unit tests
python3 -m pytest tests/test_coding_diffusion.py -v

# Quick benchmark on PI
python3 scripts/benchmark_quick.py qwen/qwen3-8b

# Full benchmark with custom model
MODEL=deepseek/deepseek-chat python3 scripts/benchmark_quick.py deepseek/deepseek-chat
```
