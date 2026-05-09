# CDBench Progress Log

## Project Overview
**CDBench**: Multi-Fault Debugging as a Scalable Benchmark for Code Reasoning in LLMs.  
Repo: https://github.com/dinkarjuyal/benchmark-creator  
Branch: `feature/coding-diffusion-v2`

---

## Completed Work

### 1. Benchmark Construction (sklearn domain)
- **20 hand-crafted corruptions** across 6 sklearn source files (metrics, preprocessing, linear models, ensembles, model selection)
- **13 SGS-generated corruptions** via three-player self-play game (Proposer/Executor/Guide)
- Corruption subtlety grading (1-5 scale)
- **5 invalid corruptions identified** (3 always-MISS + 1 always-PARTIAL + 1 zero-fix-rate) — need replacement
- `CORRUPTION_CATALOG.md` — full fix-rate analysis across models

### 2. Ablation Results (5 models evaluated)
Models tested on sklearn corruptions:
| Model | Capability Tier | Key Finding |
|-------|----------------|-------------|
| deepseek-r1-0528 | Reasoning | Dominates at all levels with 32K tokens; collapses at 8K tokens (chain-of-thought overhead) |
| deepseek-chat | General chat | Degrades gracefully; competitive at high fault counts |
| qwen3-max | General | Strong mid-tier performance |
| qwen3-coder | Code-specialized | Competitive at low fault counts, collapses at 15+ bugs |
| Qwen3.5-2B | Small | Baseline low performance |

- Results in `results/ablation_*.json` and `results/ablation_results.json`

### 3. Paper Draft
- `PAPER_DRAFT.md` — Full ML research paper draft with:
  - Abstract, Introduction, Related Work, Methodology, Results, Discussion
  - Key finding: reasoning models are strongest but critically sensitive to output token budgets
  - Methodological warning about fixed token limits producing artifactual conclusions
  - Incomplete R1 evaluation at 32K (124/144 runs done)

### 4. Functional Judge (test-based scoring)
- `scripts/functional_judge.py` — Replaces text-match scoring with pytest-based evaluation:
  - T_fail discovery (offline, cached): which tests transition pass->fail per corruption
  - Per-run scoring: compose T_fail, apply model fix, run tests
  - Per-bug attribution (optional)
  - Supports Docker and venv sandbox modes
- `scripts/discover_tfail.py` — CLI for offline T_fail discovery with caching

### 5. FastAPI Domain (in progress)
- `scripts/fastapi_corruptions.py` — 20 hand-crafted corruptions across 4 FastAPI source files:
  - `dependencies/utils.py`, `routing.py`, `applications.py`, `params.py`
  - Test mapping per source file
- FastAPI v0.115.2 pip-installed in sandbox
- Editable install failed (pdm backend issue) — pip install sufficient for tests
- **fa_08 corruption** (exclude_unset/none swap) has 0 test failures — needs replacement with a more testable corruption

### 6. Evaluation Infrastructure
- `scripts/benchmark_ablation.py` — Main ablation runner (144 runs per model)
- `scripts/run_eval_local.py` — Local vLLM-based evaluation runner
- `scripts/vllm_smoketest.py` — vLLM smoke test
- `scripts/rerun_clustered.py` — Re-run failed/clustered conditions
- `scripts/functional_judge.py` — Test-based judge (see above)

### 7. GPU Infrastructure
- SSH config set up for H100 GPU access
- 32B model eval was launched on 4 H100 GPUs for sklearn
- Results should be available on the GPU server

### 8. Paper Sections (separate files)
- `paper/intro.md` — Introduction draft
- `paper/related_work.md` — Related work draft

---

## In Progress / Next Steps

1. **Fix fa_08** — Replace with a corruption that causes actual test failures in FastAPI
2. **Complete FastAPI T_fail discovery** — Run `discover_tfail.py` for FastAPI corruptions
3. **Run FastAPI ablation** — Evaluate models on FastAPI domain (multi-domain paper)
4. **32B model results** — Check H100 GPU server for completed sklearn 32B eval runs
5. **Replace 5 invalid sklearn corruptions** — hc_11, hc_15, hc_18 (always MISS), hc_04/hc_20 may need review
6. **Complete R1 32K evaluation** — 20/144 runs remaining (20-bug conditions)
7. **Finish paper** — Add FastAPI results, finalize discussion/conclusion
8. **Google Doc** — Paper at https://docs.google.com/document/d/193RwCcleGhE6SeE0wQiA9qAxTygwQCQAC5cMN8U3kuU

---

## Session History
- **May 4**: Initial benchmark construction, coding diffusion strategy, SGS generation, nutrain benchmark
- **May 5**: Ablation runs (5 models), paper framing, reframing as RL/premier ML conference paper
- **May 5-6**: DeepSeek investigation (chat vs r1), rerun with higher token budget, research report
- **May 7**: DeepSeek r1 results at 32K tokens, paper draft writing
- **May 8**: FastAPI corruption catalog, functional judge, T_fail discovery, H100 GPU setup, 32B eval launch
