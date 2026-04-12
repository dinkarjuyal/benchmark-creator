# Claude Code — Benchmark Design Notes & Work State
*Last updated: 2026-04-12. Read this FIRST before touching tasks/, scripts/, or scoring logic.*

---

## CURRENT STATE (as of last update)

### What is DONE
- **50 task directories generated** at `benchmarks/scrapy_50/tasks/` — each has `task.json`, `prompt.txt`, `public/setup.py`, `template/` (full scrapy 2.11.2 checkout + visible tests), `validator.py`
- **`benchmarks/scrapy_50/benchmark.json`** — task index with scoring metadata
- **`benchmarks/scrapy_50/docker/Dockerfile`** — evaluation image (`takehome-scrapy-mini:py312-v2`)
- **All generator scripts** at `scripts/generators/` — fully functional, see generator map below
- **Verifier builder** at `scripts/verifier_builder.py` — builds `validator.py` from TaskCandidate
- **Task writer** at `scripts/task_writer.py` — writes harness-compatible directories
- **Orchestrator** at `scripts/generate_tasks.py` — regenerate tasks from scratch with `--scrapy-root`
- **`harness/run_tasks.py`** fixed: now uses `python3 -m harness.run_task` (module invocation, not script path)
- **`scripts/analyze_results.py`** — analysis script complete
- **Full haiku benchmark run** complete — 50 tasks, results in `results/runs/`
- All code and results pushed to `https://github.com/dinkarjuyal/benchmark-creator` on branch `main`

### What is NOT DONE (next steps in order)
1. ~~Build Docker image~~ ✓
2. ~~Run full benchmark (haiku)~~ ✓
3. **Run sonnet benchmark** (optional, for 3-model comparison): `bash scripts/run_benchmark.sh sonnet`
4. **Write report** (by hand, NOT by AI) — covers design, scoring, results, shortcomings

---

## HAIKU BENCHMARK RESULTS (2026-04-12, all 50 tasks)

**Model**: `mini_claude_haiku_4_5`

| Metric | Value |
|--------|-------|
| Total tasks | 50 |
| Mean score | 0.572 |
| Score ≥ 0.9 (near-perfect) | 27 (54%) |
| Score = 0.0 (failure/timeout) | 17 (34%) |
| Pass (score ≥ 1.0) | 0 (max possible score is 0.967 due to regression_safety=0.667) |

**Score band distribution** (per deduplicated 50 tasks):
- 0.0–0.2: 17 tasks (34%) — all "agent step timed out" (5 min budget exceeded)
- 0.2–0.6: 1 task (2%) — `redirect_times_accumulation` = 0.367
- 0.6–0.9: 5 tasks (10%) — partial or near-miss fixes
- 0.9–1.0: 27 tasks (54%) — correct fix, regression-safe

**By task type** (deduplicated):
- `invariant_recovery` (44 tasks): mean ~0.58 — 27 solved cleanly, 17 failed
- `contract_extension` (3 tasks): low mean — haiku timed out on most
- `no_op` (3 tasks): 1/3 correct (haiku correctly changed nothing); 2/3 timed out looking for a non-existent bug
- `impossible` (3 tasks): 2/3 correct (haiku output `CANNOT_COMPLETE_TASK`); 1/3 timed out

**Zero-score tasks** (all agent-step timeout):
depth_middleware_init_depth, feedexport_overwrite_default, fingerprint_method_excluded,
genspider_module_name_sanitize, httperror_allow_all_flag, impossible_request_immutable_url,
noop_request_url_encoding, noop_spider_name_validation, request_add_headers_method,
settings_copy_method, settings_getbool_int_string, settings_getint_none_default,
settings_getlist_fallback_kwarg, settings_getwithbase_merge_order, spider_middleware_short_circuit,
spiderloader_list_wrong_return, spidermw_exception_continue_on_none

**Notable findings for report**:
- Regression safety is consistently 0.667 on solved tasks (1 of 4 core scrapy test files fails on every passing run) — this is a systematic issue in how the 4 regression test files were chosen; one file likely tests behavior unrelated to the fix area and consistently fails
- No-op tasks expose overconfident patching: haiku spent 5 min searching for a bug that didn't exist on 2/3 no-op tasks
- Impossible tasks mostly worked: haiku correctly recognized 2/3 as unsolvable
- The bimodal score distribution (0.0 or 0.967, very little in between) suggests the tasks are well-differentiated — either the agent finds the fix quickly or it doesn't find it at all within budget

---

## HOW TO REGENERATE TASKS FROM SCRATCH

```bash
cd benchmark-creator
# Uses existing scrapy checkout (skip re-clone):
python3 scripts/generate_tasks.py \
  --scrapy-root /path/to/scrapy-2.11.2-checkout \
  --out-dir benchmarks/scrapy_50 \
  --max 50

# Or let it clone fresh (takes ~30s):
python3 scripts/generate_tasks.py --max 50
```

The scrapy 2.11.2 clone was last at:
`/var/folders/d7/n37mhvzj7m36mdpmq6y1j7z40000gn/T/scrapy_ordfh1wv`
(tmp dir — may not persist across reboots; re-clone if missing)

---

## HOW TO RUN THE HARNESS (single task)

```bash
cd benchmark-creator
python3 harness/run_task.py \
  benchmarks/scrapy_50/tasks/settings_getint_none_default \
  --agent mini_swe_agent \
  --allow-agent-network \
  --build-missing-image
```

The harness:
1. Builds the Docker image (`takehome-scrapy-mini:py312-v2`) if missing
2. Runs `public/setup.py` inside container to apply start-state patches
3. Runs the agent (mini-swe-agent) with the task prompt
4. Runs `validator.py` to score the solution
5. Writes `result.json` with `{score, passed, message, metrics}`

---

## TASK DISTRIBUTION (50 total)

| Category | Count | Notes |
|----------|-------|-------|
| No-op | 3 | Agent must change nothing |
| Impossible | 3 | Agent must recognize infeasibility |
| Invariant Recovery (counterfactual) | 37 | AST-injected regressions to fix |
| Contract Extension | 7 | Add new capability, guard existing behavior |

**Difficulty distribution:**
- Depth 1 (single function): 6 tasks
- Depth 2 (cross-function/file): 32 tasks
- Depth 3 (cross-component): 12 tasks
- Depth 4-5 (cross-layer): 0 tasks (impossible tasks effectively at 4-5)

**Families covered:** settings, middleware, request, response, scheduler, spider, pipeline, commands, selector

---

## GENERATOR MAP

| File | Class | Output | How it works |
|------|-------|--------|-------------|
| `generators/counterfactual.py` | `CounterfactualGenerator` | 10 tasks | Single-line AST mutations to scrapy source; find→replace |
| `generators/structural_mining.py` | `StructuralMiningGenerator` | 27 tasks | Same find→replace pattern, mined from wider set of scrapy subsystems |
| `generators/contract_extension.py` | `ContractExtensionGenerator` | 7 tasks | Hardcoded new-capability tasks (no start_state_patches, agent adds code) |
| `generators/noop_impossible.py` | `NoopImpossibleGenerator` | 6 tasks | Hardcoded no-op and impossible tasks |

All generators return `list[TaskCandidate]` via `.generate()`.

---

## KEY ASSUMPTIONS (VERIFY IF THINGS BREAK)

### Scrapy version
- **Pinned at tag `2.11.2`** (NOT 2.12.0 — that tag doesn't exist on GitHub)
- All `find` strings in `INJECTIONS` / `STRUCTURAL_INJECTIONS` are verified against 2.11.2 source
- If scrapy source is updated, re-verify all injection strings (run `--dry-run` first)

### Harness contract
- The harness writes `/artifacts/runtime_context.json` with step results
- `validator.py` reads that file and `context["container_run_dir"]` to find the workspace
- The agent works in `/work` inside the container; scrapy source is at `/work/scrapy/`
- `setup.py` applies `start_state_patches` at runtime into `/work` (not into the template)

### Scoring
- `score = 0.6*hidden + 0.2*visible + 0.1*regression_safety + 0.1*policy_quality`
- For no-op/impossible tasks: any edit to scrapy source → `policy_quality = 0.0`
- `regression_safety` runs 4 core test files: test_settings, test_http_request, test_http_response, test_dupefilters
- A score ≥ 0.9 is considered "passed"

### Task writer assumptions
- `template/` contains the full scrapy 2.11.2 source **with the injected bug already applied**
- `public/setup.py` re-applies the same patches at runtime (this is intentional redundancy — setup.py is the authoritative start state; template/ serves as a reference for the agent)
- `validator.py` is written at generation time, not at runtime

### Docker image
- Image name: `takehome-scrapy-mini:py312-v2`
- `DOCKERFILE_REL` in `task_writer.py` is `"../../docker/Dockerfile"` (relative to task dir)
- The Dockerfile installs `mini-swe-agent` and all scrapy runtime + test deps
- Does NOT install scrapy itself — the agent works on the source checkout in `/work`

### Agent configs
- Located at `agents/` (see existing configs in the repo)
- Use `mini_swe_agent` as the agent class
- Need to create configs for: claude-sonnet-4-6, claude-haiku-4-5, and one more model

---

## KNOWN ISSUES / GOTCHAS

1. **`response_text_wrong_encoding` task** — the injected change is a docstring-only mutation (minimal behavioral impact). This task will likely score high even without a fix. Consider replacing with a more impactful injection if time permits.

2. **`scheduler_has_pending_always_false`** — the visible test only checks that an empty scheduler returns False (which is correct in both buggy and fixed code). The hidden test is also weak. This task may have too-easy visible tests. Not critical to fix.

3. **Contract extension tasks have no `start_state_patches`** — agent starts with clean scrapy source and must add the new capability from scratch. This is intentional but harder to score than counterfactual tasks.

4. **`template/` is huge** — each task dir contains a full scrapy checkout (~8k files). This makes the repo large. Consider a `.gitignore` that excludes `template/` and regenerates at evaluation time if repo size is a concern.

5. **No smoke test run yet** — validator.py has not been exercised end-to-end inside Docker. If the harness `/artifacts/runtime_context.json` format differs from what `validator.py` expects, all tasks will score 0.0. Verify with one smoke test before running the full benchmark.

---

## REPORT THESIS (for the human writing the report)

1. **Why unsaturated**: tasks require discovering invariants, not pattern-matching on issue descriptions; no-op and impossible tasks penalize overconfident agents; dependency depth ≥ 2 means single-function edits won't solve most tasks
2. **Why the scoring design matters**: exact match rewards scaffolding tricks; our 4-component formula rewards behavioral correctness + regression safety + edit economy
3. **Why Scrapy**: contamination argument (niche internals vs. scikit-learn), verifier stability (pure pytest, no network), CPU feasibility
4. **Aha moments**: no-op tasks (all tested models over-patched), impossible tasks (models attempted impossible changes), policy_quality penalty caught models that touched unnecessary files
5. **Design principles borrowed**: ETH Zurich adversarial benchmarks (no-op), SWE-bench lessons (avoid direct PR replay), equivalence testing (compare to reference, not exact output), spec-first generation (spec → test → solution → prompt)

---

## Core Thesis (for Report)

The benchmark is **unsaturated** because tasks require non-local, multi-step reasoning rather than pattern-matching on familiar bug shapes. A model that learned "if test fails → find nearest changed line" will score poorly. Task families are designed to expose distinct capability gaps.

---

## Required Task Diversity (ALL three must be present)

### 1. No-op Tasks (3 present)
Working code where the correct answer is **"change nothing"**. Agent should recognize behavior is already correct and not introduce regressions.
- Source: ETH Zurich adversarial SWE-bench literature (overconfident patching)
- Detection: `policy_quality` sub-score penalizes edits when `is_noop=True`

### 2. Impossible Tasks (3 present)
Prompts describing behavior changes that **cannot be achieved** given codebase constraints.
- `impossible_sync_download_in_async_engine`: make HTTP/1.1 sync in async engine
- `impossible_request_immutable_url`: make Request URL immutable after construction
- `impossible_zero_memory_cache`: zero-memory HTTP cache

### 3. Graded Difficulty Tasks (44 present)
Majority of tasks, with partial credit available via hidden/visible test split.

---

## Contamination Argument

**Scrapy is a better contamination story than scikit-learn:**
- scikit-learn is massively over-represented in training data
- Scrapy internals (scheduler dedup, middleware call chains, spider contract edge cases) are niche
- Pinned commit + behavioral prompts for anti-contamination
- No direct replay of public benchmark instances

---

## Scoring System

### Score Bands
| Range | Meaning |
|-------|---------|
| 0.0 – 0.2 | Invalid patch, does not run, or breaks task setup |
| 0.2 – 0.6 | Partial behavior recovery; some hidden tests pass |
| 0.6 – 0.9 | Solves core behavior but leaves regressions or contract violations |
| 0.9 – 1.0 | Semantically correct, robust, regression-safe |

### Primary Formula
```
score = 0.6 * hidden_test_fraction
      + 0.2 * visible_test_fraction
      + 0.1 * regression_safety
      + 0.1 * policy_quality
```

---

## Scrapy Pinned Version
**`2.11.2`** — `v2.12.0` tag does not exist on GitHub. Use `--branch=2.11.2` when cloning.
