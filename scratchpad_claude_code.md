# Claude Code — Benchmark Design Notes
*Last updated: 2026-04-11. Read before touching tasks/, scripts/, or scoring logic.*

---

## Core Thesis (for Report)

The benchmark is **unsaturated** because tasks require non-local, multi-step reasoning rather than pattern-matching on familiar bug shapes. A model that learned "if test fails → find nearest changed line" will score poorly. Task families are designed to expose distinct capability gaps.

---

## Required Task Diversity (ALL three must be present)

### 1. No-op Tasks (~3)
Working code where the correct answer is **"change nothing"**. Agent should recognize behavior is already correct and not introduce regressions.
- Source: ETH Zurich adversarial SWE-bench literature (overconfident patching)
- Detection: `policy_quality` sub-score penalizes edits when `is_noop=True`
- Report angle: reveals overconfident patching behavior in all tested models

### 2. Impossible Tasks (~3)
Prompts describing behavior changes that **cannot be achieved** given codebase constraints (e.g. protocol-level invariant, async/sync conflict).
- Agent should submit a no-change patch or explain why it's not feasible
- Report angle: tests calibration — does the model know what it doesn't know?

### 3. Graded Difficulty Tasks (~44)
Majority of tasks, with partial credit available via hidden/visible test split.

---

## Contamination Argument

**Scrapy is a better contamination story than scikit-learn:**
- scikit-learn is massively over-represented in training data (ML tutorials, Stack Overflow, papers, Kaggle)
- A contamination-safe pipeline would need to be much stronger for scikit-learn
- Scrapy internals (scheduler dedup, middleware call chains, spider contract edge cases) are niche
- Still: pin a specific commit, avoid tasks mapping 1:1 to existing GitHub issues, use behavioral prompts not issue numbers

**Anti-contamination measures:**
- Pinned commit (v2.12.0) with canary strings in templates
- Task prompts describe *behavior*, not issue numbers
- No direct replay of public benchmark instances
- Prefer counterfactual injections over verbatim PR replay

**Key report line:** "A contamination pipeline would have been much more critical for scikit-learn than for Scrapy. We focus instead on curation and task family design."

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

- `hidden_test_fraction`: proportion of hidden checks passed (not shown to agent)
- `visible_test_fraction`: proportion of public tests passed (agent can run these)
- `regression_safety`: 1.0 if no forbidden regressions; penalized per broken contract
- `policy_quality`: edit economy (penalize excessive file churn), invalid runs, no-op detection

### Optional RL-Oriented Scores (log only, not in primary score)
- Tool use efficiency (steps used vs. minimum needed)
- Number of failed intermediate runs before submission
- Step budget score (fraction of budget consumed)

### Why Not Exact Match
Exact match rewards superficial scaffolding (add `assert True`). Our formula rewards behavioral correctness + regression safety. A scorer should reflect more than exact patch match.

### Verifier Architecture
Hybrid: **test execution + structural checks** (better than either alone).
- Visible tests → agent can see and run; validator checks
- Hidden tests → only validator runs; never exposed to agent
- Structural checks → AST-based (signature intact? class hierarchy preserved?)
- Optional LLM judge → for `policy_quality` sub-score

---

## Task Type Taxonomy (SAS — Systematically Novel)

| Type | Description |
|------|-------------|
| **Invariant Recovery** | A hidden abstraction invariant is broken; agent must discover and restore it |
| **Contract Extension** | Add new capability without breaking prior behavior |
| **Cross-Layer Alignment** | Implementation + tests + docs + error messages must all agree |
| **Behavioral Refactoring** | Restructure internals while preserving all public behavior invariants |
| **Semantic Equivalence** | Two code paths should produce identical behavior; one has drifted |
| **Test Oracle Construction** | Agent must write the *right* tests, not just satisfy existing ones |
| **No-op** | Code is correct; agent must not change behavior |
| **Impossible** | Task cannot be achieved; agent should recognize and not over-patch |

---

## Task Generation Strategies

### A: Counterfactual Regression Injection (PRIMARY — ~30 tasks)
Inject subtle regression into known-good code. Visible test shows symptom. Hidden tests verify restoration.
- Fast to create, low leakage, controlled difficulty, deterministic verifiers
- Mutations: swap `>=`/`>`, flip boolean, wrong default, drop guard, remove call in chain

### B: Structural Task Mining (~10 tasks)
Mine codebase for natural task sources:
- Sibling API asymmetries (`Response.copy()` handles X, `Request.copy()` doesn't)
- `# TODO` / `# FIXME` near interface boundaries
- Functions with only happy-path tests → add edge case as hidden test
- Docstring parameters not validated in implementation

### C: Contract Extension (~7 tasks)
Describe a new capability; visible test checks new behavior; hidden tests guard existing behavior.
- Example: "Settings.getlist() should accept a fallback= kwarg like getbool() does"

### D: No-op / Impossible (~6 tasks)
- No-op: misleading prompt suggesting a bug exists; correct answer is no change
- Impossible: behavioral goal requiring a protocol-level or architectural invariant violation

---

## Task Acceptance / Rejection Criteria

### Accept if ALL of:
- Pinned start state (specific commit + file state)
- Prompt has a clear behavioral objective
- Automatic verification (tests + structural checks, no human judgment)
- Partial credit achievable (hidden + visible test split)
- At least one non-local reasoning step (cross-file, cross-layer, multi-function)
- Generation recipe is reusable across repos

### Reject if ANY of:
- One-line local repair with no reasoning required
- Direct replay of a public benchmark instance
- Depends on flaky external services or network
- Scored only by exact match
- Impossible to verify without human judgment

---

## Most Promising Scrapy Task Families

1. Download + spider middleware semantics (call order, `process_exception` chain)
2. Scheduler dedup, retry, throttling behavior
3. Request/Response processing invariants (`.copy()`, `.replace()`, `.cb_kwargs`)
4. Item pipeline and exporter behavior
5. Settings/config priority and type coercion mismatches
6. Docs–code divergence around framework behavior

---

## Scrapy Weaknesses (acknowledge in report)

- Some interesting tasks risk depending on crawling/network behavior → mock heavily
- Novelty real but lower than e.g. DSPy (less esoteric internals)
- Methodology less portable than SQLAlchemy (many tasks are framework-specific)

---

## Technical Design Principles

- **Equivalence testing**: compare behavior vs. reference implementation, not exact output
- **Spec-first generation**: spec → test → solution → task description (not the reverse)
- **Dependency depth as difficulty metric**: not code volume — count distinct files/classes agent must reason about
- **Temporal versioning**: pinned commit + behavioral prompts for anti-contamination
- **Hybrid verifiers**: test execution + LLM judge > either alone
- **Multi-dimensional scoring**: the four-component formula above

---

## Scrapy Pinned Version
**`v2.12.0`** — validate existing 5 tasks still pass before generating new ones.
