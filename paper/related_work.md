# 2. Related Work

## 2.1 LLM Debugging Benchmarks

**DebugBench** (Tian et al., ACL 2024) is the most directly comparable prior work on LLM debugging evaluation. It injects bugs into LeetCode solutions using GPT-4, creating a taxonomy of 4 bug categories (syntax, reference, logic, multiple types) across C++, Java, and Python. However, each DebugBench instance contains exactly **one injected bug**. Their "multiple" category refers to bug *type* taxonomy, not multiple co-present bugs. DebugBench cannot measure how performance degrades with bug count because bug count is always 1.

**SWE-bench** (Jimenez et al., 2023) and its extensions — **SWE-bench Verified**, **SWE-bench Pro** (Scale AI, 2025) — evaluate agents on real GitHub issues requiring repository-level code changes. These benchmarks have driven significant progress, with frontier agents now resolving 40–72% of issues. However, each task is a single issue with uncontrolled difficulty: there is no way to compare models on "3-bug problems" versus "10-bug problems" because the benchmark does not parameterize complexity. SWE-bench Pro targets enterprise-level difficulty but still evaluates isolated issues.

**Defects4J** (Just et al., 2014) and **BugsInPy** (Widyasari et al., 2020) provide curated collections of real bugs from Java and Python projects respectively. These are the standard datasets for automated program repair (APR) research but, like SWE-bench, contain one bug per entry.

Our work differs from all of the above by introducing **bug count as a controllable experimental variable**. Rather than evaluating on a fixed set of individually-curated bugs with unknown relative difficulty, we inject N controlled corruptions and measure how the per-bug fix rate degrades as N scales.

## 2.2 Long-Horizon Code Agents

**SWE-EVO** (Thai et al., 2025) directly addresses the long-horizon limitation of existing benchmarks. Constructed from release notes of seven open-source Python projects, SWE-EVO tasks require multi-step modifications spanning an average of 21 files, with test suites averaging 874 tests. GPT-5.4 with OpenHands achieves only 25% on SWE-EVO versus 72.8% on SWE-bench Verified, demonstrating a striking capability gap for sustained multi-file reasoning. However, SWE-EVO tasks are *feature implementation*, not *debugging*, and each task is unique — difficulty cannot be compared across tasks or parameterized.

**NL2Repo-Bench** (2025) evaluates agents on generating complete repositories from natural language specifications. **SWE-bench Pro** targets complex, enterprise-level issues. Both confirm that multi-file reasoning is a bottleneck but provide no mechanism to *control* the complexity axis.

Our work complements these efforts by providing a controlled debugging-specific complexity axis. Where SWE-EVO measures "can the agent handle a complex task?", we measure "at what point does the agent's debugging capability break down, and why?"

## 2.3 Multi-Fault Program Debugging

**Callaghan & Fischer (MSR 2025)** is the closest prior work to our multi-bug evaluation setting. They extend Defects4J and BugsInPy to identify multiple naturally co-occurring bugs in the same program version, using test case transplantation and fault location translation. This produces datasets of *real* multi-fault programs.

However, their approach differs fundamentally from ours in two ways: (1) they *mine* naturally co-occurring bugs from version history, meaning the number and type of co-present bugs are determined by whatever happened to exist — they cannot control the bug count; (2) their focus is on providing realistic multi-fault datasets for traditional APR tools, not on measuring how LLM debugging capability scales with controlled complexity. Our synthetic injection approach sacrifices naturalism for experimental control: we can hold individual bug difficulty constant while varying the count, spatial distribution, and source, producing the first debugging difficulty curves.

## 2.4 Synthetic Bug Generation

**Synthetic Code Surgery** (2025) uses LLMs to generate synthetic bugs for training APR systems. Their contribution is a data generation pipeline for improving repair models, not a benchmark methodology. They generate single bugs for training, not compositions of N bugs for evaluation.

**Meta's Automated Compliance Hardening (ACH)** (2025) uses mutation-guided, LLM-based test generation to harden platforms against regressions. Their mutations serve as test oracles rather than debugging tasks.

**DebugBench** uses GPT-4 to inject bugs following predefined templates. Our SGS (Suggest-Guide-Score) pipeline extends this idea with adversarial quality control: a proposer LLM suggests corruptions, an executor verifies behavioral change, and a guide LLM scores non-triviality — rejecting bugs that are too easy, too syntactic, or produce identical outputs. This produces higher-quality corruptions at a 65% acceptance rate.

## 2.5 Positioning

| Property | DebugBench | SWE-bench | SWE-EVO | Multi-Fault (MSR'25) | **CDBench (Ours)** |
|---|---|---|---|---|---|
| Bugs per task | 1 | 1 | N/A (features) | 2–5 (mined) | **1–20 (controlled)** |
| Difficulty control | Bug type only | None | None | None | **Bug count, distribution, source** |
| Degradation curves | No | No | No | No | **Yes** |
| Spatial distribution | N/A | N/A | Multi-file | Uncontrolled | **Clustered vs. scattered** |
| Bug source | GPT-4 injection | Real issues | Release notes | Real co-occurring | **Hand-crafted + SGS adversarial** |
| Scoring | Pass/fail | Patch match | Fix rate | FL accuracy | **Per-bug fix rate conditioned on N** |
| Real codebases | LeetCode | GitHub repos | GitHub repos | Defects4J/BugsInPy | **sklearn, nutrain** |
| Phase transitions | Not studied | Not studied | Not studied | Not studied | **Observed and characterized** |
