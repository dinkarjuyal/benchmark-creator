# Scaling Debugging Complexity: A Controlled Benchmark for Long-Horizon Code Repair

## Abstract

We introduce CDBench (Compositional Debugging Benchmark), a methodology for evaluating LLM debugging capability under controlled compositional complexity. Unlike existing benchmarks that evaluate agents on isolated, individually-curated bug fixes, CDBench injects a variable number N of single-point corruptions into real library source code and measures per-bug fix rates as N scales. This produces the first continuous difficulty dial for debugging evaluation: by varying bug count, spatial distribution (clustered vs. scattered across files), and corruption source (hand-crafted vs. adversarially generated), we systematically map the boundary of each model's "debugging horizon." Experiments on scikit-learn and a real ML training framework (nutrain) with five models reveal three key findings: (1) models exhibit a **sharp phase transition** rather than gradual degradation — qwen3-coder fixes 100% of bugs at N≤3 but collapses to 0% at N=10 on nutrain; (2) **spatial distribution matters as much as count** — at N=20, deepseek-chat fixes 70% of clustered bugs but only 20% of scattered bugs; (3) **semantic bugs are systematically harder than syntactic ones** regardless of bug count, with non-crashing logic errors fixed <50% of the time. We release the benchmark, a 3-player adversarial bug generation pipeline (SGS), and a corruption catalog for reproducibility.

---

## 1. Introduction

Large language models have achieved impressive results on code repair benchmarks. On SWE-bench Verified, frontier agents now resolve over 70% of real-world GitHub issues, and on simpler benchmarks like HumanEval-Fix, near-perfect scores are common. These results suggest that LLM-based debugging may be approaching human-level competence.

But this conclusion rests on a flawed evaluation methodology. Existing debugging benchmarks — SWE-bench, DebugBench, Defects4J — share a critical limitation: **each task contains exactly one bug**. Difficulty is an uncontrolled property of whatever bug happened to exist in the repository. There is no way to ask "how does Model A compare to Model B on 5-bug problems?" because 5-bug problems do not exist in these benchmarks. More fundamentally, there is no way to measure how debugging capability *degrades* as problem complexity scales, because complexity is not a controllable parameter.

This matters because real-world debugging is rarely about a single isolated defect. A developer debugging a failing CI pipeline may face multiple interacting issues: a logic error in the business layer that masks a race condition in the data layer, or a cascade of off-by-one errors introduced during a refactor that touch a dozen files. The question is not *whether* a model can fix a bug, but *how many simultaneous bugs exhaust its reasoning capacity* — and how that capacity varies with the spatial structure of the bugs across the codebase.

### Debugging as a Sequential Decision Problem

We frame multi-bug debugging as a compositional reasoning task with parallels to long-horizon planning in reinforcement learning. An agent fixing N bugs must:

1. **Explore**: identify which regions of code are buggy among a potentially large codebase
2. **Reason**: determine the correct fix for each bug, distinguishing the corruption from intentional code
3. **Assign credit**: verify that each fix addresses its target bug without introducing regressions or masking other bugs

As N increases, the agent faces a combinatorial explosion in the joint reasoning space. Each additional bug expands the hypothesis space (is this code wrong, or is it wrong because of an interaction with another bug?), lengthens the context the agent must hold in working memory, and increases the probability that one incorrect fix cascades into others. This is directly analogous to the compounding error problem in long-horizon RL, where small per-step errors accumulate to make multi-step plans unreliable.

We hypothesize that LLM debugging exhibits a **phase transition**: near-perfect performance up to some model-specific bug count k, then rapid collapse beyond k. The value k — the model's effective **debugging horizon** — is the key quantity our benchmark is designed to measure.

### Contributions

1. **A controllable compositional complexity axis for debugging.** We introduce the first benchmark where difficulty is a continuous, tunable parameter (bug count N) rather than an uncontrolled property of individual issues. The same bugs appear across conditions, enabling controlled comparison.

2. **Phase transition in debugging performance.** We provide the first empirical evidence that LLM debugging exhibits sharp capability cliffs, not gradual degradation. On real ML training code, qwen3-coder transitions from 100% fix rate at N=3 to 0% at N=10 — every bug unfixed, including trivial ones it solved perfectly in isolation.

3. **Spatial distribution as a difficulty dimension.** We demonstrate that *where* bugs are located matters as much as *how many* there are. At N=20 on scikit-learn, deepseek-chat fixes 70% of bugs clustered in one file but only 20% when scattered across modules. This implicates cross-file reasoning, not per-bug difficulty, as the bottleneck.

4. **Adversarial bug generation via a 3-player game.** We introduce SGS (Suggest-Guide-Score), an automated pipeline where a proposer LLM suggests corruptions, an executor verifies they change behavior, and a guide LLM filters for non-triviality. This enables scalable benchmark construction without manual curation, producing bugs at a 65% acceptance rate with quality comparable to hand-crafted corruptions.

### Key Findings Preview

On **nutrain** (a real mixture-of-experts training framework):
- Models fix 100% of bugs at N≤3 regardless of subtlety
- Performance drops to 71–80% at N=5–7 as subtle bugs start being missed
- At N=10, qwen3-coder scores 0% — complete collapse, not gradual decline
- The AdaLN `(1+scale) → scale` bug (subtlety 2) is consistently missed by all models at N≥5, even though it's trivial in isolation

On **scikit-learn** (6 source files, 20 hand-crafted + 13 SGS corruptions):
- 1–5 bugs: 80–100% fix rate on valid corruptions
- 7–10 bugs: 60–90% depending heavily on spatial distribution
- 15–20 scattered bugs: drops to 20–50% — the long-horizon debugging limit for deepseek-chat
- Semantic bugs (set membership changes, accumulation strategy flips) are fixed <50% regardless of N; syntactic bugs (operator swaps, invalid axes) are fixed >80%

These results establish that **the debugging horizon is real, measurable, and model-specific** — opening a new evaluation axis for code agent research.
