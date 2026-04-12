#!/usr/bin/env python3
"""Run multiple benchmark tasks, optionally with parallelism and repeated trials.

The batch runner is intentionally thin:
- it delegates actual execution to `run_task.py`
- each trial gets its own workspace and container set
- parallelism is bounded at the task-trial level

This keeps task execution isolated while still letting us scale local sweeps.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run multiple tasks and emit an aggregate summary."
    )
    parser.add_argument(
        "tasks",
        nargs="*",
        help="Task directories. If omitted, use --benchmark or discover all tasks.",
    )
    parser.add_argument(
        "--benchmark",
        help="Benchmark id under --benchmark-registry, without the .json suffix.",
    )
    parser.add_argument(
        "--benchmark-registry",
        default=str(ROOT / "benchmarks"),
        help="Directory containing benchmark registries.",
    )
    parser.add_argument(
        "--results-dir",
        default=str(ROOT / "results" / "runs"),
        help="Directory where run artifacts are written.",
    )
    parser.add_argument(
        "--build-missing-image",
        action="store_true",
        help="Build missing task images when task.json provides a dockerfile.",
    )
    parser.add_argument(
        "--keep-run-dir",
        action="store_true",
        help="Keep copied task workspaces under the result directories.",
    )
    parser.add_argument(
        "--n-parallel",
        type=int,
        default=1,
        help="Maximum number of tasks to execute in parallel.",
    )
    parser.add_argument(
        "--num-trials",
        type=int,
        default=1,
        help="Number of independent trials to run per task.",
    )
    parser.add_argument(
        "--agent-command",
        help="Escape hatch for directly specifying the agent step command.",
    )
    parser.add_argument(
        "--agent-config",
        help="Path to an agent_config.yaml applied to each task run.",
    )
    parser.add_argument(
        "--agent",
        help="Agent config name under --agent-registry, without the .yaml suffix.",
    )
    parser.add_argument(
        "--agent-registry",
        default=str(ROOT / "agents"),
        help="Directory containing reusable agent_config.yaml files.",
    )
    parser.add_argument(
        "--allow-agent-network",
        action="store_true",
        help="Allow outbound network access during each agent step.",
    )
    return parser.parse_args()


def discover_tasks() -> list[Path]:
    task_paths = list((ROOT / "tasks").glob("**/task.json"))
    task_paths.extend((ROOT / "benchmarks").glob("**/tasks/**/task.json"))
    return sorted(path.parent for path in task_paths)


def load_benchmark(benchmark_registry: Path, benchmark_id: str) -> tuple[str, list[Path]]:
    benchmark_path = benchmark_registry / benchmark_id / "benchmark.json"
    if not benchmark_path.exists():
        benchmark_path = benchmark_registry / f"{benchmark_id}.json"
    if not benchmark_path.exists():
        raise SystemExit(f"error: benchmark not found: {benchmark_id}")
    raw = json.loads(benchmark_path.read_text())
    benchmark_root = benchmark_path.parent
    task_dirs = [(benchmark_root / task_dir).resolve() for task_dir in raw.get("task_dirs", [])]
    return raw.get("name", benchmark_id), task_dirs


def run_one(task_dir: Path, args: argparse.Namespace, trial_index: int) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_task.py"),
        str(task_dir),
        "--results-dir",
        args.results_dir,
        "--trial-index",
        str(trial_index),
    ]
    if args.agent_command:
        cmd.extend(["--agent-command", args.agent_command])
    elif args.agent_config:
        cmd.extend(["--agent-config", args.agent_config])
    else:
        cmd.extend(["--agent", args.agent, "--agent-registry", args.agent_registry])
    if args.build_missing_image:
        cmd.append("--build-missing-image")
    if args.keep_run_dir:
        cmd.append("--keep-run-dir")
    if args.allow_agent_network:
        cmd.append("--allow-agent-network")

    completed = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
    )
    payload: dict[str, Any] | None = None
    if completed.stdout.strip():
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = None

    return {
        "task_dir": str(task_dir),
        "trial_index": trial_index,
        "exit_code": completed.returncode,
        "result": payload,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> int:
    args = parse_args()
    if args.n_parallel < 1:
        print("error: --n-parallel must be at least 1", file=sys.stderr)
        return 2
    if args.num_trials < 1:
        print("error: --num-trials must be at least 1", file=sys.stderr)
        return 2
    if sum(bool(value) for value in [args.agent_command, args.agent_config, args.agent]) != 1:
        print(
            "error: provide exactly one of --agent-command, --agent-config, or --agent",
            file=sys.stderr,
        )
        return 2

    benchmark_name = None
    if args.tasks:
        task_dirs = [Path(task).resolve() for task in args.tasks]
    elif args.benchmark:
        benchmark_name, task_dirs = load_benchmark(Path(args.benchmark_registry).resolve(), args.benchmark)
    else:
        task_dirs = discover_tasks()
    if not task_dirs:
        print("error: no tasks found", file=sys.stderr)
        return 2

    jobs = [
        (task_dir, trial_index)
        for task_dir in task_dirs
        for trial_index in range(args.num_trials)
    ]

    runs: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.n_parallel) as executor:
        future_to_index = {
            executor.submit(run_one, task_dir, args, trial_index): index
            for index, (task_dir, trial_index) in enumerate(jobs)
        }
        ordered_runs: list[dict[str, Any] | None] = [None] * len(jobs)
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            ordered_runs[index] = future.result()
        runs = [run for run in ordered_runs if run is not None]

    passed = sum(
        1
        for run in runs
        if run["result"] and float(run["result"]["validation"].get("score", 0.0)) >= 1.0
    )
    task_summaries: list[dict[str, Any]] = []
    for task_dir in task_dirs:
        task_runs = [run for run in runs if run["task_dir"] == str(task_dir)]
        task_passes = sum(
            1
            for run in task_runs
            if run["result"] and float(run["result"]["validation"].get("score", 0.0)) >= 1.0
        )
        task_summaries.append(
            {
                "task_dir": str(task_dir),
                "num_trials": len(task_runs),
                "num_passed": task_passes,
                "pass_rate": task_passes / len(task_runs),
            }
        )
    summary = {
        "benchmark": benchmark_name,
        "num_tasks": len(task_dirs),
        "num_task_trials": len(runs),
        "num_trials": args.num_trials,
        "num_passed": passed,
        "pass_rate": passed / len(runs),
        "n_parallel": args.n_parallel,
        "task_summaries": task_summaries,
        "runs": runs,
    }
    print(json.dumps(summary, indent=2))
    return 0 if passed == len(runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
