# Scrapy Task Selection Methodology

This document describes the current method we use to generate, rank, and
select Scrapy benchmark tasks in a systematic way.

## Overall Summary

We mine recent high-signal issues and PRs, tag them by failure directions that
are hard for current agents, derive a relevance score from those tags, and then
rank candidates using a rubric that prioritizes agent-weakness relevance,
novelty, and high-quality hardness over generic bug complexity. We then select
from the top-ranked pool while enforcing coverage across different agent-hard
directions so that the final benchmark is both systematic and diverse.

We do not optimize for generic bug difficulty. We optimize for task directions 
that are difficult for current coding agents for the right reasons, such as non-local reasoning,
compatibility, lifecycle ordering, and invariant preservation.


## What We Are Optimizing For

We want benchmark tasks that:

- require real repository understanding
- are deterministic and validator-friendly
- test one clear behavioral contract
- are difficult because of reasoning and coordination, not because of flaky
  setup or underspecification
- expose failure modes that current agents still struggle with

## Step 1: Generate A Broad Candidate Pool

We begin by mining a broad set of task sources instead of hand-picking
individual issues. The point of this stage is recall: collect many plausible
task reservoirs, then filter and rank them later.

### Source Classes We Mine

Current candidate generation focuses on the following source classes:

- recent large merged PRs
- recent issues with clear behavioral reports
- issue/PR pairs that provide both problem statement and likely fix surface
- adjacent tests, docs, and implementation files around those issues/PRs
- compatibility, migration, and deprecation work that can be sliced into narrow
  behavior-preserving tasks

### Why These Sources

These source classes are useful for different reasons:

- large merged PRs are often reservoirs for multiple narrow tasks, especially
  compatibility and async-transition work
- issues provide user-visible failure descriptions, which are useful for
  turning vague code changes into explicit behavioral contracts
- issue/PR pairs reduce ambiguity because the issue explains the symptom while
  the PR suggests the true code surface
- adjacent tests and docs help us define guardrails so tasks cannot be solved by
  overfitting to a single failing path

### Mining Heuristics

The current mining pass uses explicit heuristics:

- favor recent artifacts, especially late-2025 and 2026 changes, to reduce task
  saturation
- favor artifacts touching async behavior, lifecycle management, config
  precedence, subprocess/project context, cache/storage logic, and state
  invariants
- prefer candidates whose likely fixes are multi-file or non-local
- avoid docs-only, CI-only, or broad architectural efforts in the first wave

### Candidate Normalization

Each mined source is normalized into a structured candidate record with fields
such as:

- source type and reference
- module area
- primary capability
- hard-direction tags
- expected benchmark shape
- notes on likely slicing opportunities

This normalization step is important because it makes heterogeneous sources
comparable. A large PR, an issue, and a mutation-guided proposal can all enter
the same ranking pipeline once they are represented with the same schema.

For Scrapy, this process has yielded candidate families around:

- async lifecycle and completion behavior
- command and project-context handling
- config precedence and project discovery
- compatibility-preserving async migrations
- narrow policy, warning, and state-invariant regressions

## Step 2: Tag Each Candidate By Agent-Hard Directions

Each candidate is tagged with one or more hard directions that reflect failure
patterns we expect from current agents. These tags are the core of the
methodology because they define why a task is benchmark-valuable.

These tags matter more than repository area alone. Two tasks may both live in
`scrapy/core/`, but only one may actually test a difficult agent weakness.

### Definitions Of The Hard Directions

`cross_file_causality`

- The visible failure occurs in one part of the repository, but the correct fix
  requires changing another file or layer.
- This stresses the agent's ability to trace cause and effect across module
  boundaries instead of patching the closest surface symptom.
- Typical examples include middleware-manager interactions, command code that
  fails because of project-discovery helpers, or cache middleware behavior that
  is actually controlled by storage abstractions.

`implicit_invariants`

- Correctness depends on preserving behavior that is not explicitly stated at
  the point of failure.
- The agent must infer and preserve nearby contracts from surrounding code,
  tests, or analogous paths.
- Typical examples include maintaining callback output semantics while adding a
  warning, preserving middleware ordering while changing async behavior, or
  preserving request-copy semantics while fixing a mutation bug.

`async_or_lifecycle_ordering`

- Correctness depends on when work happens, when it completes, or in what order
  multiple stages run.
- This includes awaited completion, shutdown semantics, startup ordering,
  backpressure, and callback sequencing.
- These tasks are hard for agents because local fixes often pass superficial
  checks while breaking completion, ordering, or cleanup behavior.

`environment_and_context`

- Behavior depends on runtime context outside the immediate function body, such
  as current working directory, import path, subprocess environment, project
  root discovery, or event-loop context.
- These tasks stress whether the agent can reason about execution context rather
  than only in-process logic.
- Typical examples include CLI commands inside projects, shell behavior under an
  installed reactor, and configuration discovery from different roots.

`behavioral_parity`

- Two similar code paths, APIs, or commands should behave consistently, and the
  task is to restore or preserve that consistency.
- This often appears during migrations or feature additions where one path has
  been updated and the other has not.
- These tasks are useful because agents often fix the targeted path without
  checking analogous paths or backward-compatible behavior.

`state_aliasing`

- The failure is caused by shared mutable state, shallow copying, reused
  containers, or unintended object coupling.
- The agent must reason about ownership and mutation rather than only values at
  one point in time.
- Typical examples include copied requests sharing cookie/header state or lazy
  object internals leaking mutation across instances.

`policy_edge_cases`

- The core logic is mostly correct, but behavior is wrong under a narrow set of
  statuses, priorities, flags, or precedence combinations.
- These tasks are valuable because they require understanding the intended
  policy boundary rather than only the happy path.
- Typical examples include status-sensitive throttling, settings precedence,
  cache expiration, or warning behavior conditioned on compatibility mode.

`serialization_roundtrip`

- Correctness depends on preserving data across a representation boundary such
  as cache storage, filesystem representation, config parsing, or object
  reconstruction.
- The agent must reason about what information must survive write/read or
  encode/decode operations.
- These tasks are distinct from simple parsing bugs because they involve
  bidirectional contracts and lossless reconstruction.

`partial_feature_slices`

- The source artifact is larger than a single benchmark task, and we extract one
  narrow contract from it.
- This is a task-design property rather than a code property: it tells us the
  source should be mined as a reservoir and turned into small, precise tasks.
- Typical examples include taking one awaited-storage contract from a large async
  cache PR or one warning-preservation behavior from a larger compatibility
  migration.

### What These Tags Are Used For

We use these tags for three things:

- to decide whether a candidate is benchmark-relevant at all
- to derive `agent_weakness_relevance`
- to enforce coverage when selecting the final task set

Examples:

- a task that requires changing downloader behavior while preserving middleware
  ordering would score high on `cross_file_causality`,
  `implicit_invariants`, and `async_or_lifecycle_ordering`
- a task around `genspider --edit` would score high on
  `environment_and_context` and `behavioral_parity`
- a task around request copying would score high on `state_aliasing`

## Step 3: Screen Out Bad Candidates

After mining, we filter out candidates that are poor benchmark tasks even if
they are real repository issues.

We reject or down-rank candidates that are:

- too easy and solvable by editing the nearest line to a failing assertion
- broad feature requests rather than narrow behavioral contracts
- hard mainly because they are ambiguous
- hard mainly because they require large environment setup
- likely flaky or nondeterministic
- overly saturated or too similar to common public benchmark tasks

This is important because real repository issues are not automatically good
benchmark tasks.

## Step 4: Score Candidates With A Structured Rubric

For the candidates that survive screening, we assign rubric scores. The scoring
is systematic rather than intuitive.

Current scored dimensions:

- `agent_weakness_relevance`
- `anti_saturation`
- `hardness_quality`
- `locality`
- `determinism`
- `implementation_cost`
- `guardrailability`

The most important field is `agent_weakness_relevance`. This is not assigned by
gut feeling. It is derived from the hard-direction tags.

### How We Interpret The Most Important Criteria

`agent_weakness_relevance`

- high if the task strongly hits one or more directions that are known to be
  hard for current agents
- highest if it combines multiple strong directions, such as cross-file
  causality plus implicit invariants plus environment handling
- low if it mostly reduces to a local patch

`anti_saturation`

- high if the task shape is unlikely to be memorized from existing public evals
- high if it comes from recent PRs, compatibility changes, or narrow local
  slices that are not standard benchmark fare

`hardness_quality`

- high if the task is hard because it requires reasoning, navigation,
  sequencing, or preserving invariants
- low if the task is hard because the task is vague, noisy, or flaky

`locality`

- not "smallest diff wins"
- instead, we prefer tasks that are locally implementable but require
  understanding beyond a single line or assert

`determinism`

- high if the task can be validated with offline, stable, task-local tests

## Step 5: Compute A Weighted Ranking

We combine the rubric into a weighted ranking.

Current weighted score:

`2 * agent_weakness_relevance + 2 * anti_saturation + 2 * hardness_quality + locality + determinism`

This weighting reflects our priorities:

- first, choose tasks that target real current-agent weaknesses
- second, prefer tasks that are novel and not benchmark-saturated
- third, prefer tasks that are hard in a high-quality way
- then use locality and determinism as practical tie-breakers

This makes the ranking legible and defensible. It is clear why a candidate
rises or falls.

## Step 6: Rank First, Then Slice

We rank candidate sources before final task implementation. High-ranked issues
and PRs are treated as reservoirs that may yield one or more tasks.

This matters because a large PR is rarely one benchmark task. Instead, we slice
it into narrow contracts.

Examples of slicing:

- a large async migration PR becomes one task about awaited cache retrieval
- a large compatibility PR becomes one task about preserving warning behavior
- a broad issue about project discovery becomes one task about a single
  precedence rule

The unit of ranking is the source candidate. The unit of implementation is the
task slice.

## Step 7: Select For Coverage Across Hard Directions

We do not simply take the top N scores. Final selection also checks benchmark
coverage.

We want the accepted task set to span multiple hard directions, such as:

- async/lifecycle ordering
- environment/context handling
- compatibility-preserving migrations
- state aliasing and mutation
- config precedence
- policy edge cases

This prevents the benchmark from becoming repetitive even if several
high-scoring candidates come from the same family.

In practice, selection works like this:

1. rank the full candidate pool
2. take the top tier as the default shortlist
3. slice those sources into concrete tasks
4. ensure the resulting task set covers multiple hard directions
5. drop duplicates in task shape even if they came from different PRs


## Why This Is Systematic

This process is systematic because:

- candidate generation comes from reusable source classes, not one-off picks
- selection is based on explicit tags and rubric dimensions
- the key relevance score is derived from hard-direction tags
- ranking uses a fixed weighted formula
- final selection includes a coverage check instead of intuition alone

That makes the approach easier to scale across more Scrapy tasks and, in
principle, to other repositories.

## Current Output Artifacts

The current process produces these concrete artifacts:

- `candidate_inventory.jsonl`: mined candidate records
- `candidate_scores.csv`: scored rubric table
- `CANDIDATE_RANKING.md`: ranked shortlist and rationale
- `TOP_5_TASKS_AND_EVAL.md`: concrete top-task slices and evaluation design

Together, these artifacts make the pipeline inspectable from mining through
selection.
