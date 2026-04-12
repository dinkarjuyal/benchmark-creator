# Top 5 Task Specs And Evaluation

This document turns the highest-ranked mined candidates into 5 concrete task
specs and defines how they should be evaluated.

The design principle for evaluation is:

- use binary scoring when the task has one crisp behavioral contract
- use weighted scoring only when the task has a natural main objective plus
  meaningful guardrails
- never use weights to hide a vague validator

## Why Weighted Evaluation At All?

Weighted evaluation is useful only when:

- there is a clearly dominant regression we care about
- there are nearby invariants that should still matter
- partial success is meaningful and diagnostically useful

Weighted evaluation is not useful when:

- the task is a single crisp contract
- partial credit would reward overfitting
- the guardrails are too weak to interpret independently

For these top 5 tasks, the right pattern is:

- binary scoring for the fully crisp CLI and config tasks
- weighted scoring for async lifecycle and compatibility tasks where the main
  regression and the guardrails can fail independently

## Task 1: Wait For Async Pipelines From `start()`

- Source: `#7029`
- Task ID: `start_items_pipeline_wait`
- Capability: `async_lifecycle`
- Hard directions:
  `async_or_lifecycle_ordering`, `cross_file_causality`, `implicit_invariants`

### Contract

Items yielded directly from a spider's `start()` method must fully complete
their pipeline processing before the crawl is considered finished.

### Why this is benchmark-worthy

- symptom and fix are not co-located
- requires engine/scraper/pipeline reasoning
- agents can easily patch the wrong lifecycle point
- guardrails matter because a naive fix may stall or alter normal request flow

### Likely files touched

- `scrapy/core/engine.py`
- `scrapy/core/scraper.py`
- pipeline management helpers if needed

### Validator shape

One focused pytest module with:

- primary regression: async pipeline completion is awaited for items from
  `start()`
- guardrail: normal request-yielding `start()` behavior is unchanged
- guardrail: crawl still finishes cleanly with synchronous pipelines

### Recommended scoring

Weighted:

- `0.6` primary async completion regression
- `0.2` request-flow guardrail
- `0.2` synchronous-pipeline guardrail

Why weighted:

The main contract is the core of the task, but nearby lifecycle invariants are
important enough that they should affect score without fully collapsing it.

## Task 2: `genspider --edit` Uses The Correct Project Context

- Source: `#7340` / `#7260`
- Task ID: `genspider_edit_project_context`
- Capability: `cli_context`
- Hard directions:
  `environment_and_context`, `behavioral_parity`, `cross_file_causality`

### Contract

Running `scrapy genspider --edit <name> <domain>` inside a project should behave
like running `genspider` first and then `edit` inside that same project and
Python environment.

### Why this is benchmark-worthy

- subprocess behavior depends on cwd and project-local imports
- agents must reason about command chaining and environment propagation
- the intended behavior is easy for a human to explain but easy for agents to
  mishandle with ad hoc subprocess fixes

### Likely files touched

- `scrapy/commands/genspider.py`
- command bootstrap or helper code for project detection

### Validator shape

One focused subprocess-based pytest module with:

- generate a temporary project
- run `scrapy genspider --edit`
- assert successful exit
- assert spider file created
- assert no project import failure

### Recommended scoring

Binary:

- `1.0` all assertions pass
- `0.0` otherwise

Why binary:

This is a crisp behavioral parity contract. Partial credit would mostly reward
broken command chaining.

## Task 3: Surface Pipeline `from_crawler` Errors Cleanly

- Source: `#7092`
- Task ID: `pipeline_from_crawler_error_surface`
- Capability: `async_lifecycle`
- Hard directions:
  `cross_file_causality`, `implicit_invariants`, `environment_and_context`

### Contract

If an item pipeline declares `from_crawler` incorrectly or raises during setup,
the crawl process should surface the error clearly instead of continuing or
failing in a misleading way.

### Why this is benchmark-worthy

- startup/component wiring bugs are a real weakness for current agents
- the failure may manifest far from the real cause
- agents often patch around symptoms instead of fixing initialization flow

### Likely files touched

- pipeline loading or component manager code
- crawler startup/extension bootstrapping code

### Validator shape

One focused pytest module with:

- primary regression: invalid pipeline setup raises a clear failure during crawl
  startup
- guardrail: valid `from_crawler` pipelines still load normally
- guardrail: unrelated pipeline loading paths remain unchanged

### Recommended scoring

Weighted:

- `0.7` primary error-surfacing regression
- `0.15` valid-pipeline guardrail
- `0.15` unrelated-loading guardrail

Why weighted:

The central benchmark value is correct error surfacing. The guardrails matter,
but they are secondary.

## Task 4: Async HTTP Cache Storage Slice

- Source: `#7404`
- Task ID: `httpcache_async_storage_contract`
- Capability: `serialization`
- Hard directions:
  `partial_feature_slices`, `serialization_roundtrip`, `cross_file_causality`

### Scope constraint

Do not benchmark the whole PR. Slice it to one narrow contract:

- async cache storage methods should be awaited correctly by the cache pipeline
  or middleware boundary

Possible concrete slice:

- persisting a cached response through an async storage backend must complete
  before the middleware reports success

### Why this is benchmark-worthy

- tests async compatibility at a storage boundary
- requires implementing exactly enough of a larger feature
- agents are prone to adding partial async support without preserving round-trip
  behavior

### Likely files touched

- `scrapy/extensions/httpcache.py`
- `scrapy/downloadermiddlewares/httpcache.py`
- storage helper abstractions

### Validator shape

One focused pytest module with:

- primary regression: async storage write or read path is awaited and completes
- guardrail: synchronous storage path still works
- guardrail: cached metadata/body round-trip remains correct

### Recommended scoring

Weighted:

- `0.5` async storage completion
- `0.25` sync storage compatibility
- `0.25` cache round-trip correctness

Why weighted:

This is a textbook staged task: main async feature slice plus two essential
backwards-compatibility and correctness checks.

## Task 5: Downloader Middleware `download_async()` Compatibility Slice

- Source: `#7069`
- Task ID: `downloadermiddleware_async_compat`
- Capability: `compatibility`
- Hard directions:
  `cross_file_causality`, `implicit_invariants`, `partial_feature_slices`

### Scope constraint

Do not benchmark the full async API migration. Slice it to one compatibility
contract:

- downloader middleware should support the narrow async path required by the
  regression tests without regressing existing synchronous behavior

Possible concrete slice:

- an async middleware path should be awaited correctly while legacy middleware
  behavior still works

### Why this is benchmark-worthy

- async migration tasks are realistic and currently hard for agents
- the fix is likely distributed across middleware manager and call sites
- naive fixes often break older code paths

### Likely files touched

- `scrapy/core/downloader/middleware.py`
- call sites that bridge sync and async middleware execution

### Validator shape

One focused pytest module with:

- primary regression: async middleware path returns the expected response or
  request and is awaited correctly
- guardrail: legacy synchronous middleware path still passes
- guardrail: middleware ordering semantics remain unchanged

### Recommended scoring

Weighted:

- `0.55` async middleware regression
- `0.25` sync compatibility guardrail
- `0.20` ordering/semantics guardrail

Why weighted:

The main difficulty is the async compatibility slice, but preserving legacy
behavior is a core part of the task.

## Benchmark-Level Evaluation

For the benchmark as a whole, we should score tasks in two layers.

### Task-Level Score

Each task returns a score in `[0,1]` using either:

- binary scoring for crisp single-contract tasks
- weighted subtest scoring for staged tasks with meaningful guardrails

### Benchmark Aggregate Score

The benchmark should report:

- unweighted mean task score
- mean by capability family
- mean by hard-direction family
- success rate at score `1.0`

Recommended primary headline metric:

- unweighted mean task score

Why:

- it is easiest to interpret
- it avoids hiding failures in one task family behind overperformance in another
- it keeps the benchmark comparison simple

Recommended secondary metrics:

- async/lifecycle subset mean
- CLI/context subset mean
- compatibility subset mean
- fraction of tasks with guardrail failures despite main regression passing

## Evaluation Methodology Summary

The evaluation methodology should be described as:

1. Choose recent, unsaturated candidates that target known current-agent
   weaknesses.
2. Slice each source into one narrow behavioral contract.
3. Use binary scoring when the task is crisp and indivisible.
4. Use weighted scoring only when there is a clear main regression plus
   independent guardrails.
5. Report both overall mean score and breakdowns by capability and hard
   direction.

This gives us evaluations that are more informative than a flat pass/fail rate
without making the scoring arbitrary.
