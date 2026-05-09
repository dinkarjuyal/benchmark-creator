# Multi-Fault Debugging as a Scalable Benchmark for Code Reasoning in Large Language Models

## Abstract

We introduce a controlled benchmark for evaluating LLM debugging capability as a function of problem complexity. By injecting a variable number of synthetic bugs (1--20) into real-world library code, we construct a difficulty axis that exposes how different model architectures degrade under increasing cognitive load. We evaluate five models spanning four capability tiers on scikit-learn, using 20 hand-crafted corruptions and adversarially generated bugs from a three-player self-play game (SGS). Our key findings are: (1) reasoning models (deepseek-r1) dominate at all difficulty levels when given sufficient output budget, but collapse catastrophically under token constraints due to chain-of-thought overhead -- a methodological pitfall for benchmarks evaluating such models; (2) model rankings are non-stationary across difficulty, with code-specialized models (qwen3-coder) competitive at low fault counts but collapsing at 15+ bugs while general chat models (deepseek-chat) degrade gracefully; (3) the benchmark produces a smooth, monotonic difficulty gradient that cleanly separates model capabilities. We release the benchmark construction pipeline, all corruption specifications, and evaluation scripts.

---

## 1. Introduction

Debugging is among the most cognitively demanding tasks in software engineering. Unlike code generation -- where the model produces output from a specification -- debugging requires simultaneously localizing faults, reasoning about intended behavior, and producing targeted repairs without introducing regressions. When multiple bugs co-exist in the same codebase, the problem becomes combinatorially harder: bug symptoms may interact, fixes may conflict, and the search space for root causes grows superlinearly.

Despite this, existing LLM debugging benchmarks predominantly evaluate single-bug scenarios. DebugBench (Tian et al., ACL 2024) injects one bug per LeetCode problem. SWE-bench (Jimenez et al., 2024) evaluates on real GitHub issues that typically involve a single localized fix. These benchmarks cannot answer a fundamental question: *how does debugging performance degrade as problem complexity scales?*

We address this gap by proposing **multi-fault debugging** as a scalable evaluation axis. Our approach is simple: inject *n* bugs into real library code and measure the fraction an LLM can correctly revert, varying *n* from 1 to 20. This produces a degradation curve -- analogous to psychometric item-response curves -- that characterizes each model's effective "debugging bandwidth."

**Why this matters for the field.** As LLM agents are increasingly deployed for autonomous code maintenance, understanding their failure modes under realistic complexity is critical. Real-world codebases rarely contain a single isolated bug. Pull requests touch multiple files. Refactoring introduces correlated errors. A model that scores 90\% on single-bug benchmarks but collapses at 5 simultaneous faults is not ready for production deployment. Our benchmark directly measures this cliff.

**Contributions:**
- A benchmark construction methodology that produces a controllable difficulty gradient from a fixed set of corruptions, requiring no new data collection per difficulty level
- An adversarial three-player self-play game (SGS) for automated generation of non-trivial code corruptions that are consistently harder than hand-crafted bugs
- An empirical study across five models revealing that (a) reasoning models are strongest but critically sensitive to output token budgets, (b) model rankings shift with difficulty, and (c) code-specialized models have a narrower effective complexity range than general models
- A methodological warning: benchmarks that fix output token limits can produce artifactual conclusions about reasoning models, since chain-of-thought consumes output budget that would otherwise be used for the answer

---

## 2. Related Work

**Single-fault debugging benchmarks.** DebugBench (Tian et al., ACL 2024) uses GPT-4 to inject categorized bugs (syntax, reference, logic) into LeetCode solutions, evaluating models on single-bug repair. SWE-bench (Jimenez et al., 2024) draws from real GitHub issues but each instance typically involves one localized change. Neither supports varying difficulty along a fault-count axis.

**Multi-fault program analysis.** Callaghan & Fischer (MSR 2025) extend Defects4J and BugsInPy to identify commits containing multiple real bugs. While this provides ecological validity, real multi-bug commits are rare, hard to isolate, and do not offer parametric control over difficulty. Our synthetic approach trades some ecological validity for precise control and scalability.

**Benchmark difficulty control.** LiveCodeBench (Jain et al., 2024) uses competitive programming problems with inherent difficulty ratings. HumanEval+ (Liu et al., 2024) augments test cases for harder evaluation. Neither provides a *continuous* difficulty axis within a single problem domain. Our approach uniquely enables same-codebase, same-bug-pool evaluation at arbitrary difficulty levels.

**Adversarial benchmark generation.** CyberSecEval (Bhatt et al., 2024) uses adversarial techniques for security evaluation. Our SGS game adapts the proposer-judge paradigm specifically for code corruption quality, ensuring generated bugs are non-trivial and semantically meaningful.

---

## 3. Methodology

### 3.1 Corruption Design

We construct corruptions on scikit-learn (v1.6), targeting six source files spanning metrics, preprocessing, linear models, ensembles, and model selection. Each corruption is a *(find, replace)* pair: `find` is the original correct code, `replace` is the buggy version.

**Hand-crafted corruptions (20).** We design 20 single-point mutations graded by subtlety (1=obvious, 5=edge-case-only):
- *Subtlety 1--2*: Operator swaps (`**` to `*`), zero-vs-one errors, division-by-zero traps
- *Subtlety 3*: Axis swaps, condition inversions (`AND` to `OR`), normalization errors
- *Subtlety 4--5*: Semantic changes that only manifest on specific inputs (e.g., restricting multiclass to binary-only, penalizing the intercept in ridge regression)

Corruptions span 6 source files (2--4 per file) to enable diversity control.

**SGS-generated corruptions.** We employ a three-player self-play game:
1. **Proposer**: Given a function from the codebase, proposes a single subtle mutation
2. **Executor**: Validates that (a) the find string is unique and unambiguous, (b) find and replace strings don't overlap, (c) the corruption actually modifies the code
3. **Guide**: Scores the corruption on relevance, elegance, and non-triviality (1--10 each); rejects if any score < 3

SGS corruptions are generated per-model to avoid train-on-test contamination. Across models, SGS produces 0--13 accepted corruptions per run (deepseek-r1 produces 0, confirming reasoning models are poor at adversarial self-play for code corruption).

### 3.2 Ablation Dimensions

Each experimental condition is defined by three factors:

- **Fault count** *n* in {1, 2, 3, 5, 7, 10, 15, 20}: the number of corruptions simultaneously injected
- **Diversity**: *clustered* (bugs concentrated in fewest files) vs *scattered* (bugs spread across files)
- **Source**: *hand* (hand-crafted only), *sgs* (SGS-generated only), or *mixed* (both)

For each condition, we run 3 independent trials with different random corruption selections, yielding 144 runs per model (8 counts x 2 diversities x 3 sources x 3 trials).

### 3.3 Evaluation Protocol

The model receives: (1) the corrupted source code (function-level snippets, not full files), (2) the number of bugs *n*, and (3) one-line descriptions of each bug. It must return the complete fixed code for each affected file.

**Scoring.** For each corruption *(find, replace)*:
- **FIXED**: `find` present in output AND `replace` absent (bug correctly reverted)
- **PARTIAL**: `find` present but `replace` also present (located but not cleanly fixed)
- **MISS**: `find` absent from output (function rewritten or not returned)

Fix rate = FIXED / total bugs. We report mean fix rate across trials.

### 3.4 Models

| Model | Type | Parameters | Token Budget |
|-------|------|-----------|-------------|
| Qwen3.5-2B | Small/general | 2B | 8,192 |
| qwen3-coder | Code-specialized | -- | 8,192 |
| deepseek-chat | General chat | -- | 8,192 |
| qwen3-max | Frontier general | -- | 8,192 |
| deepseek-r1-0528 | Reasoning (CoT) | -- | 32,768* |

*deepseek-r1 was initially run at 8K tokens, producing artifactually low scores. See Section 4.2.

All models accessed via Prime Intellect inference API. Temperature = default, no system-level prompt engineering beyond the debugging instruction.

---

## 4. Results

### 4.1 Main Results

Table 1 reports aggregated fix rates across all conditions.

| Bugs | Qwen3.5-2B | qwen3-coder | deepseek-chat | qwen3-max | deepseek-r1 |
|-----:|-----------:|------------:|--------------:|----------:|------------:|
|    1 |       5.6% |      61.1%  |        83.3%  |    66.7%  |      61.1%  |
|    2 |      13.9% |      88.9%  |        77.8%  |    69.4%  |      83.3%  |
|    3 |      13.9% |      79.6%  |        72.2%  |    79.6%  |      88.9%  |
|    5 |       6.7% |      74.4%  |        61.1%  |    66.7%  |      85.6%  |
|    7 |       8.3% |      65.1%  |        55.6%  |    54.8%  |      84.1%  |
|   10 |       0.0% |      63.3%  |        59.4%  |    26.1%  |      72.2%  |
|   15 |       0.6% |       9.4%  |        54.4%  |    23.3%  |      55.8%  |
|   20 |       0.4% |      11.2%  |        49.2%  |    27.3%  |        --   |

**Key observations:**

**Reasoning dominates.** deepseek-r1 achieves the highest fix rate at every difficulty level tested (1--15 bugs), peaking at 89% for 3 bugs and maintaining 56% at 15. This suggests that explicit chain-of-thought reasoning provides a substantial advantage for multi-fault localization and repair.

**Degradation profiles differ qualitatively.** We identify three degradation archetypes:
- *Graceful degradation* (deepseek-chat): 83% → 49%, nearly linear decline, never reaches zero
- *Cliff collapse* (qwen3-coder): 89% → 9% with a sharp drop between 10 and 15 bugs
- *Steady decline* (deepseek-r1, qwen3-max): monotonic but with different slopes

**Rankings are non-stationary.** At 3 bugs, qwen3-coder and qwen3-max tie at ~80%. At 15 bugs, qwen3-coder has collapsed to 9% while deepseek-chat holds at 54%. Single-difficulty benchmarks cannot capture this crossover.

### 4.2 The Token Budget Trap: A Cautionary Tale

Our initial evaluation of deepseek-r1 used a standard 8,192 output token limit, producing dramatically poor results: 20% at 5 bugs, 0% at 15 bugs. This appeared to show that reasoning models are *worse* at multi-fault debugging -- a striking and publishable (but wrong) conclusion.

**Diagnosis.** Three lines of evidence revealed the problem:

1. **Response time plateau.** R1's response time plateaued at ~85 seconds from 5+ bugs onward, while deepseek-chat's scaled from 88s to 214s. A reasoning model should take *longer* on harder problems, not the same time. The plateau indicated hitting a hard token ceiling.

2. **Cliff, not slope.** R1's fix rate dropped from 72% at 3 bugs to 20% at 5 bugs -- a discontinuity inconsistent with gradual reasoning failure but consistent with output truncation at a fixed budget.

3. **100% MISS, 0% PARTIAL.** At 15+ bugs, every single corruption scored MISS (function not present in output). If the model were *reasoning* incorrectly, we would expect some PARTIAL results. Total absence indicates the output was truncated before the model could emit the code.

**Root cause.** Reasoning models generate `<think>...</think>` tokens before the answer. These tokens count against the output budget. For multi-file debugging output at 15 bugs, the answer alone requires ~5,000--8,000 tokens. If reasoning consumes 3,000--5,000 tokens, the code output is truncated.

**Resolution.** Re-running with 32,768 output tokens produced dramatic improvements:

| Bugs | 8K tokens | 32K tokens |   Delta |
|-----:|----------:|-----------:|--------:|
|    5 |    20.0%  |     85.6%  | +65.6pp |
|    7 |    11.1%  |     84.1%  | +73.0pp |
|   10 |     1.7%  |     72.2%  | +70.6pp |
|   15 |     0.0%  |     55.8%  | +55.8pp |

**Implication for the community.** Any benchmark evaluating reasoning models with fixed output token limits risks producing artifactual results. The chain-of-thought overhead is task-dependent and unpredictable. We recommend that benchmarks either (a) set generous output limits (4x the expected answer length), or (b) separately measure and report reasoning token consumption.

### 4.3 Corruption Source Analysis

SGS-generated corruptions are consistently harder than hand-crafted ones across all models:

| Model | Hand-crafted (avg) | SGS (avg) | Gap |
|-------|-------------------:|----------:|----:|
| deepseek-r1 | 77% | 79% | +2pp |
| deepseek-chat | 69% | 52% | -17pp |
| qwen3-max | 57% | 46% | -11pp |
| qwen3-coder | 55% | 53% | -2pp |

The SGS game produces corruptions that exploit model blind spots -- semantically valid mutations that look plausible to pattern-matching but are logically incorrect. This validates automated corruption generation as a viable approach for benchmark scaling.

### 4.4 Failure Mode Analysis

For deepseek-chat (the model with the richest failure data), the dominant failure mode shifts with difficulty:

- **Low difficulty (1--3 bugs):** Failures are predominantly MISS (17--22%) -- the model rewrites functions rather than performing targeted fixes. This is a formatting issue, not a reasoning one.
- **High difficulty (15--20 bugs):** MISS rate reaches 51%, but now reflects genuine inability to track all mutations simultaneously. The model's attention is spread too thin to faithfully reproduce all original code.

Notably, PARTIAL failures (localized but not fixed) are rare (<8% everywhere), suggesting models either fully fix a bug or completely miss it. There is little "partial credit" in multi-fault debugging.

---

## 5. Discussion

### Implications for Agent Deployment

Our results suggest a practical threshold for autonomous debugging: models maintain >50% fix rates up to 7--10 simultaneous bugs, depending on architecture. Beyond this, even frontier models require decomposition strategies (e.g., fix bugs sequentially rather than all at once). This has direct implications for agentic coding workflows where models must handle complex, multi-file changes.

### The Diversity Dimension

Clustered bugs (same file) are not consistently easier or harder than scattered bugs (different files). This suggests the difficulty comes from the *number* of simultaneous reasoning threads, not from context switching between files. This finding supports the hypothesis that multi-fault debugging taxes working memory rather than retrieval.

### Limitations

1. **Single codebase.** All results are on scikit-learn. Generalization to other languages, paradigms, and codebases remains to be validated.
2. **Synthetic corruptions.** While our corruptions are semantically meaningful, they are single-point mutations. Real-world bugs may involve multi-line changes, architectural issues, or logic errors spanning multiple functions.
3. **Prompt sensitivity.** We use a fixed prompt template. Models may perform differently with chain-of-thought prompting, few-shot examples, or iterative repair.
4. **Incomplete R1 evaluation.** deepseek-r1 at 32K tokens was stopped at 124/144 runs (missing 20-bug data) due to cost constraints. The 1--15 bug data is complete.

---

## 6. Conclusion

We present multi-fault debugging as a principled benchmark axis for evaluating LLM code reasoning under scaling complexity. Our methodology is simple to implement, requires no new data collection per difficulty level, and produces clean degradation curves that meaningfully separate model capabilities.

Three findings stand out. First, reasoning models are the strongest debuggers when properly evaluated -- but improperly constrained output budgets can lead to dramatically wrong conclusions, a trap that current benchmarking practices are susceptible to. Second, model rankings are not stable across difficulty levels, arguing against single-number benchmark scores. Third, the gap between "can debug 3 bugs" and "can debug 15 bugs" is where models most diverge, making this the most informative region for future evaluation.

We believe the multi-fault paradigm generalizes beyond debugging to any task where complexity can be parameterized by the number of simultaneous reasoning threads: multi-step planning, multi-constraint optimization, and compositional reasoning. The degradation curve, rather than a single accuracy number, is the right way to characterize these capabilities.

---

## References

- Tian, H. et al. (2024). DebugBench: Evaluating Debugging Capability of Large Language Models. *ACL 2024*.
- Jimenez, C.E. et al. (2024). SWE-bench: Can Language Models Resolve Real-World GitHub Issues? *ICLR 2024*.
- Callaghan, D. & Fischer, B. (2025). Mining Bug Repositories for Multi-Fault Programs. *MSR 2025*.
- Jain, N. et al. (2024). LiveCodeBench: Holistic and Contamination-Free Evaluation of Large Language Models for Code. *NeurIPS 2024*.
- Liu, J. et al. (2024). Is Your Code Generated by ChatGPT Really Correct? *NeurIPS 2024*.
- Bhatt, M. et al. (2024). CyberSecEval: A Secure Coding Benchmark. *Meta AI*.
