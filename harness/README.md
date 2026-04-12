Reusable harness code lives here.

Main entrypoints:

- `python3 harness/run_task.py <task_dir> ...`
- `python3 harness/run_tasks.py --benchmark <benchmark_id> ...`
- `python3 harness/run_tasks.py benchmarks/scrapy/tasks/settings_equal_priority_override --agent mini_claude_haiku_4_5 --allow-agent-network --keep-run-dir`


Key concepts:

- `harness/agents/`: class-based agent adapters and the adapter registry
- `agents/`: reusable agent config files that select one adapter plus its settings
- task interface: one task directory with `task.json`, `prompt.txt`, optional
  `public/`, `template/`, and validation logic
- benchmark registry: a `benchmark.json` file listing task directories, usually
  alongside benchmark-local `tasks/` and `docker/` folders

Agent flow:

1. `run_task.py` loads the selected `agent_config.yaml`.
2. The harness resolves the named adapter from `harness/agents/registry.py`.
3. The adapter subclass builds the concrete in-container command for that agent.
4. The harness calls `adapter.run(...)` to execute the agent step in Docker.


Examples:

python3 run_task.py benchmarks/take_home_demo/tasks/uppercase_file --agent mini_deterministic --keep-run-dir
python3 run_tasks.py --benchmark take_home_demo --agent mini_deterministic --num-trials 2 --n-parallel 2 --keep-run-dir