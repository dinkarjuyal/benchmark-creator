# Scrapy Benchmark

This benchmark packages a focused snapshot of the Scrapy repository into the
local harness.

Included today:

- Docker image definition for a Scrapy-capable Python 3.12 runner
- a methodology-derived task set focused on lifecycle, context, compatibility, and policy behavior
- a lightweight repo snapshot under the task template so runs stay fast

Task summary:

- workspace contains a trimmed Scrapy checkout with the real `scrapy/` package
- the agent-visible workspace comes from `template/`
- hidden regression tests live under task-local `hidden_tests/`
- validation runs those hidden pytest targets against the copied workspace


Archived tasks:

- older hand-authored tasks that predate the current candidate-generation methodology live under `tasks/old/`
- they are kept for reference, but are not part of the active benchmark manifest

Suggested commands:

```bash
python3 scripts/run_task.py benchmarks/scrapy/tasks/start_items_pipeline_wait --agent mini_deterministic --build-missing-image
python3 scripts/run_tasks.py --benchmark scrapy --agent mini_deterministic --build-missing-image
```
