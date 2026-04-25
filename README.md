<div align="center">

# 🧪 benchmark-creator

**Turn any Python library into a behavioral benchmark for LLMs — in one command**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-90%20passing-brightgreen.svg)](tests/)

**Point → Generate → Evaluate**

*Automatically discover where models are confidently wrong about a library's behavior*

[How It Works](#-how-it-works) • [Quick Start](#-quick-start) • [Benchmarks](#-included-benchmarks) • [Architecture](#-architecture) • [Contributing](#-contributing)

</div>

---

## ✨ What It Does

Give it a GitHub repo URL. It reads the README, extracts behavioral families, and runs an adversarial two-player game to find questions where a model *knows a rule* but *applies it where it breaks*.

Every question is **execution-verified** — Python runs both the confirming case and the confounder before the question is accepted. No hallucinated outputs.

<div align="center">

| 🎭 **Adversarial** | 📚 **Knowledge** | 🔬 **SGS** |
|:---:|:---:|:---:|
| *"The rule holds here — does it hold here too?"* | *"What does this code print?"* | *"Adversarial + Guide quality filter"* |
| Two-player game: rule + boundary case | Direct behavioral prediction | Guide scores each confounder before accepting |
| Tests overgeneralization | Tests API calibration | Filters degenerate confounders (import errors, output shuffles) |
| Execution-verified confounder | Execution-verified output | ~30% more API calls, higher-quality confounders |

</div>

---

## 🚀 Quick Start

```bash
git clone https://github.com/dinkarjuyal/benchmark-creator.git
cd benchmark-creator
pip install anthropic scikit-learn pandas

# Generate adversarial + knowledge tasks for any Python library
ANTHROPIC_API_KEY=sk-ant-... python3 -m benchmark_creator \
  --repo https://github.com/scikit-learn/scikit-learn \
  --strategy adversarial,knowledge \
  --n 2 \
  --max-tasks 5 \
  --output benchmarks/my_benchmark
# [seed] 1745123456  (rerun with --seed 1745123456 to reproduce this question set)

# Use the SGS strategy for higher-quality confounders (Guide filters degenerate cases)
ANTHROPIC_API_KEY=sk-ant-... python3 -m benchmark_creator \
  --repo https://github.com/scikit-learn/scikit-learn \
  --strategy sgs \
  --n 2 \
  --max-tasks 5 \
  --output benchmarks/my_benchmark_sgs
```

**Each run generates a fresh question set by default** (seed = Unix timestamp). To reproduce an exact set, pass `--seed <N>` with the printed value. Keep your evaluation seeds private — don't commit `generation_stats.json` to a public repo if you're running a blind evaluation.

**Output:**
```
benchmarks/my_benchmark/
  benchmark.json          ← task registry
  tasks/<task_id>/        ← harness-compatible task dirs
    prompt.txt            ← question shown to the agent
    validator.py          ← scores agent's /work/answer.json
    task.json             ← metadata: image, timeout, correct answer
  meta/
    repo_profile.json     ← extracted families + seed rules
    generation_stats.json ← candidates tried vs. kept
```

---

## 🎯 How It Works

### The Adversarial Game

```
Repo README
    ↓
RepoAnalyzer          "What are the behavioral rules practitioners know?"
    ↓                  → families: [preprocessing_scaling, nan_handling, ...]
Player 1 (Proposer)   "Here's a rule + a snippet that confirms it"
    ↓                  Rule: "StandardScaler uses training stats, not test stats"
    ↓                  Confirming: scaler.fit([10,20,30]); transform([100]) → 9.79
Player 2 (Adversary)  "Here's where that rule breaks non-obviously"
    ↓                  Confounder: scaler.fit([10,20,30]); scaler.fit([100,200,300]);
    ↓                              transform([100]) → -1.22  ← rule predicts 9.79!
Python executor       Runs both snippets. Rejects if outputs match.
    ↓
[Guide scorer]        Rates confounder on relevance + elegance + non-triviality
    ↓                 Rejects degenerate cases (import errors, output-order shuffles)
MCTaskCandidate       4-choice question, hard negative = rule naively applied
```

**The key insight:** distractors aren't random wrong answers — the hard negative is always *the output the rule predicts*, which is what a model confidently applying a known rule would choose. Getting it wrong reveals systematic overgeneralization, not just a knowledge gap.

**The Guide prevents confounder collapse.** Without a quality filter, the Adversary can "win" by generating trivially different output (e.g. an `ImportError`, or shuffling two printed values). The Guide scores each confounder on three axes (relevance, elegance, non-triviality) and forces a retry if any score is below threshold — the same mechanism as Self-Guided Self-Play (SGS).

### Example Question (scikit-learn)

```
Rule: StandardScaler applies training mean/variance to test data

Confirming case (rule holds):
  scaler.fit([[10],[20],[30]])
  print(scaler.transform([[100]])[0][0])
  → 9.797958971132712

Question: What does this print?

  scaler.fit([[10],[20],[30]])
  scaler.fit([[100],[200],[300]])   ← called fit() again
  print(scaler.transform([[100]])[0][0])

  A. -1.224744871391589   ← CORRECT (second fit overwrites stats)
  B. -1.0
  C. 0.0
  D. 9.797958971132712    ← hard negative (rule naively applied)
```

---

## 📦 Included Benchmarks

### 🐼 pandas — `benchmarks/pandas_understanding/`

35 tasks across two types:

| Family | Adversarial | Knowledge |
|--------|:-----------:|:---------:|
| `groupby_semantics` | ✓ | ✓ |
| `dtype_coercion` | ✓ | ✓ |
| `nan_semantics` | ✓ | ✓ |
| `index_alignment` | ✓ | ✓ |
| `copy_semantics` | ✓ | ✓ |

Plus 25 hand-curated knowledge tasks in `PANDAS_INJECTIONS` (verified against pandas 2.2.x).

### 🤖 scikit-learn — `benchmarks/scikit_learn/`

10 tasks auto-generated from the scikit-learn README:

| Family | Type | Example confounder |
|--------|------|--------------------|
| `preprocessing_scaling_behavior` | adversarial | Calling `fit()` twice overwrites scaler statistics |
| `cross_validation_data_leakage` | adversarial | When all folds have identical distribution, fold means don't differ |
| `feature_importance_interpretation` | adversarial | `feature_importances_` stops summing to 1 after `SelectFromModel` |
| `nan_handling_in_estimators` | adversarial | `SimpleImputer.transform()` uses training mean, not data passed to transform |
| `predict_proba_calibration` | adversarial | More trees can *reduce* overconfidence, not always increase it |

---

## 🔬 Running Evaluations

```bash
# Run a single task locally (no Docker required)
ANTHROPIC_API_KEY=sk-ant-... python3 -m harness.run_task \
  benchmarks/scikit_learn/tasks/adv_preproce_when_standardscaler_is_fit_on__078b9cc4 \
  --agent mini_claude_haiku_4_5_mc \
  --runtime local

# Run all tasks in a benchmark
python3 -m harness.run_tasks \
  --benchmark-dir benchmarks/scikit_learn \
  --agent mini_claude_haiku_4_5_mc \
  --runtime local
```

The agent reads `prompt.txt`, writes `{"choice": "A"}` to `/work/answer.json`.  
The validator scores: **1.0** (correct + clean) · **0.8** (correct + extra edits) · **0.0** (wrong).

---

## 🏗️ Architecture

```
benchmark-creator/
  benchmark_creator/       ← CLI entry point (python3 -m benchmark_creator)
  scripts/
    generators/
      strategy_registry.py ← GenerationStrategy ABC + StrategyRegistry plugin layer
      adversarial_mc.py    ← two-player game + GuideScorer + RepoAnalyzer +
                              strategy registrations (adversarial, knowledge, sgs)
      pandas_mc.py         ← MCTaskCandidate data model + prompt builder
      pandas_injections.py ← hand-curated pandas gold set
    verifier_builder_mc.py ← generates validator.py for each task
    task_writer_mc.py      ← writes harness-compatible task directories
  harness/
    run_task.py            ← single-task runner (Docker or local)
    run_tasks.py           ← batch runner with parallelism
    agents/
      base.py              ← AgentAdapter ABC
      mini_swe_agent.py    ← mini-swe-agent integration
  benchmarks/
    pandas_understanding/  ← 35 tasks
    scikit_learn/          ← 10 tasks
    pandas_v2/             ← 4 tasks generated with issues+commits+5Whys pipeline
  tests/                   ← 90 tests, no API key required
```

### Adding a New Strategy

Register a new generation approach in one file — no CLI changes needed:

```python
from scripts.generators.strategy_registry import register_strategy, GenerationStrategy
from scripts.generators.pandas_mc import MCTaskCandidate

@register_strategy("my_strategy")
class MyStrategy(GenerationStrategy):
    """One-line description shown in --strategy help."""

    def __init__(self, api_key: str, verbose: bool = False, seed: int | None = None):
        ...

    def generate(self, families: list[dict], n_per_family: int = 3) -> list[MCTaskCandidate]:
        ...
```

Import the module once (e.g. in `adversarial_mc.py` or the CLI) and `--strategy my_strategy` becomes available immediately.

### Adding a New Library

The generator is fully repo-agnostic. `RepoAnalyzer` fetches README + closed issues + fix commits and extracts behavioral families with 5-Whys causal reasoning:

```python
from scripts.generators.adversarial_mc import RepoAnalyzer
from scripts.generators.strategy_registry import get_strategy

sources = {
    "readme":  RepoAnalyzer.from_github("https://github.com/psf/requests"),
    "issues":  RepoAnalyzer.from_github_issues("https://github.com/psf/requests"),
    "commits": RepoAnalyzer.from_github_commits("https://github.com/psf/requests"),
}
families = RepoAnalyzer(api_key="sk-ant-...").extract_families(sources, library_name="requests")

strategy = get_strategy("sgs")(api_key="sk-ant-...")
candidates = strategy.generate(families=families, n_per_family=3)
```

---

## 🧪 Tests

```bash
pip install pytest
python3 -m pytest tests/ -v
```

52 tests, no API key required. Covers:

| File | What it tests |
|------|---------------|
| `test_tag_parsing.py` | LLM → data serialization boundary |
| `test_snippet_execution.py` | Python execution verifier + timeout handling |
| `test_mc_candidate.py` | Prompt format, choice shuffling, task ID stability |
| `test_validator.py` | Scoring: correct / wrong / dirty workspace / missing file |
| `test_generator_logic.py` | Confounder accept/reject filter; `RepoAnalyzer` parsing (mocked LLM) |

---

## 📋 CLI Reference

```
python3 -m benchmark_creator [OPTIONS]

  --repo URL         GitHub URL of the target Python library
  --strategy LIST    Generation strategy: adversarial, knowledge, sgs,
                     or comma-separated (default: inferred from --types)
  --types LIST       adversarial,knowledge  (legacy alias for --strategy)
  --n N              Questions per family per seed rule (default: 3)
  --max-tasks N      Cap tasks per strategy (e.g. --max-tasks 5)
  --seed N           RNG seed for choice shuffling (default: Unix timestamp)
  --families PATH    Pre-extracted families JSON (skips RepoAnalyzer)
  --output DIR       Output directory (default: benchmarks/<repo_name>)
  --api-key KEY      Anthropic API key (or set ANTHROPIC_API_KEY)
  --github-token T   GitHub token for higher API rate limits (optional)
  --probe            Verify seed_rules via REPL probes; drops version-mismatched rules
  --dry-run          Generate without writing task directories
```

**Strategies:**

| Strategy | Description | Extra cost |
|----------|-------------|------------|
| `adversarial` | Classic two-player game, no quality filter | baseline |
| `knowledge` | Direct behavioral-prediction questions | baseline |
| `sgs` | Adversarial + SGS Guide scorer; rejects degenerate confounders | ~30% more calls (1 haiku/confounder) |

The seed is printed at startup and stored in `meta/generation_stats.json`. Pass `--seed <N>` to reproduce a previous run's choice ordering; omit it to get a fresh draw each time (recommended for evaluations to prevent answer memorization).

---

## 🤝 Contributing

Contributions welcome. The most impactful areas:

- **New generation strategies** — implement `GenerationStrategy`, decorate with `@register_strategy("name")`, done (see "Adding a New Strategy" above)
- **More seed rules** for existing families in `adversarial_mc.py`
- **New benchmark libraries** — run the CLI and open a PR with the generated tasks
- **Git history mining** — mine commits for causal-tracing questions (Component C in architecture notes)
- **Better distractor generation** — make the non-hard-negative distractors represent tighter misconceptions

```bash
# Verify nothing is broken before opening a PR
python3 -m pytest tests/ -v
```

---

<div align="center">

**Built to find where models are confidently wrong, not just wrong**

[⭐ Star on GitHub](https://github.com/dinkarjuyal/benchmark-creator) • [🐛 Report an Issue](https://github.com/dinkarjuyal/benchmark-creator/issues) • [💡 Request a Feature](https://github.com/dinkarjuyal/benchmark-creator/issues)

</div>
