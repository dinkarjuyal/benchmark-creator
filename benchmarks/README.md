Store reusable benchmark registries here.

A benchmark is typically a self-contained directory with:

- `benchmark.json`
- `tasks/`
- optional benchmark-local `docker/`

Task paths in `benchmark.json` are resolved relative to the benchmark
directory, so tasks and Dockerfiles can live under the benchmark itself.

Suggested format:

```json
{
  "id": "take_home_demo",
  "name": "Take-home Demo Benchmark",
  "task_dirs": [
    "tasks/uppercase_file"
  ]
}
```

Suggested layout:

```text
benchmarks/
  take_home_demo/
    benchmark.json
    docker/
      harness-mini.Dockerfile
    tasks/
      uppercase_file/
        task.json
        prompt.txt
        public/
        template/
        validator.py
```
