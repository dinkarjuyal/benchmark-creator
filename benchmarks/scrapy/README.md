# Scrapy Benchmark

This benchmark packages a focused snapshot of the Scrapy repository into the
local harness.

Included today:

- Docker image definition for a Scrapy-capable Python 3.12 runner
- five focused tasks across request, settings, and command behavior
- a lightweight repo snapshot under the task template so runs stay fast

Task summary:

- workspace contains a trimmed Scrapy checkout with the real `scrapy/` package
- each task carries a small focused pytest file under `template/tests/`
- validation runs only that task-specific pytest target inside the copied workspace

Current tasks:

- `request_copy_cookies`: copied or replaced requests should not alias mutable cookies
- `settings_equal_priority_override`: same-priority writes should replace older values
- `settings_getbool_lowercase`: lowercase boolean strings should be accepted by `getbool()`
- `command_genspider_https_default`: bare domains should default to `https://` in genspider
- `command_version_prefix`: non-verbose version output should keep the `Scrapy <version>` prefix

Suggested commands:

```bash
python3 scripts/run_task.py benchmarks/scrapy/tasks/request_copy_cookies --agent mini_deterministic --build-missing-image
python3 scripts/run_tasks.py --benchmark scrapy --agent mini_deterministic --build-missing-image
```
