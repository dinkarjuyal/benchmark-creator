#!/usr/bin/env python3
"""Audit generated tasks for hidden-test discriminativeness."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class SuiteResult:
    passed: int
    total: int

    @property
    def fraction(self) -> float:
        return self.passed / self.total if self.total else 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit generated benchmark tasks.")
    parser.add_argument(
        "--benchmark-dir",
        type=Path,
        default=ROOT / "benchmarks" / "scrapy_50",
        help="Benchmark directory containing tasks/ and benchmark.json",
    )
    parser.add_argument(
        "--scrapy-root",
        type=Path,
        required=True,
        help="Path to a clean scrapy checkout pinned to the benchmark version.",
    )
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        help="Optional task id(s) to audit. Defaults to all tasks in benchmark.json.",
    )
    return parser.parse_args()


def load_validator_module(task_dir: Path) -> ModuleType:
    module_path = task_dir / "validator.py"
    spec = importlib.util.spec_from_file_location(f"audit_{task_dir.name}", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load validator module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_buggy_workspace(task_dir: Path, workspace: Path) -> None:
    shutil.copytree(task_dir / "template", workspace, dirs_exist_ok=True)


def prepare_fixed_workspace(task_dir: Path, scrapy_root: Path, workspace: Path) -> None:
    shutil.copytree(task_dir / "template", workspace, dirs_exist_ok=True)
    for name in ("scrapy", "tests"):
        src = scrapy_root / name
        dst = workspace / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

    for fname in ("pyproject.toml", "setup.py", "setup.cfg", "README.rst"):
        src = scrapy_root / fname
        if src.exists():
            shutil.copy2(src, workspace / fname)

    template_tests = task_dir / "template" / "tests"
    fixed_tests = workspace / "tests"
    if template_tests.exists():
        for visible in template_tests.glob("test_visible_*.py"):
            shutil.copy2(visible, fixed_tests / visible.name)


def run_suite(test_blocks: list[str], workspace: Path, label_prefix: str) -> SuiteResult:
    passed = 0
    total = 0
    env = {**os.environ, "PYTHONPATH": str(workspace)}
    for idx, test_code in enumerate(test_blocks):
        fd, tmp_name = tempfile.mkstemp(
            suffix=".py",
            prefix=f"_audit_{label_prefix}_{idx}_",
            dir=str(workspace),
            text=True,
        )
        os.close(fd)
        tmp_path = Path(tmp_name)
        tmp_path.write_text(test_code)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(tmp_path),
                "--tb=short",
                "-q",
                "--json-report",
                f"--json-report-file=/tmp/audit_{label_prefix}_{idx}.json",
                "-o",
                "addopts=",
            ],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            env=env,
        )
        report_path = Path(f"/tmp/audit_{label_prefix}_{idx}.json")
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text())
                passed += report["summary"].get("passed", 0)
                total += report["summary"].get("total", 0)
            finally:
                report_path.unlink(missing_ok=True)
        else:
            total += max(1, result.stdout.count("PASSED") + result.stdout.count("FAILED"))
            passed += result.stdout.count("PASSED")
        tmp_path.unlink(missing_ok=True)
    return SuiteResult(passed=passed, total=total)


def audit_task(task_dir: Path, scrapy_root: Path) -> dict[str, object]:
    validator = load_validator_module(task_dir)
    task_json = json.loads((task_dir / "task.json").read_text())
    meta = task_json.get("_meta", {})
    is_noop = bool(meta.get("is_noop"))
    is_impossible = bool(meta.get("is_impossible"))

    with tempfile.TemporaryDirectory(prefix=f"audit_buggy_{task_dir.name}_") as buggy_tmp, tempfile.TemporaryDirectory(
        prefix=f"audit_fixed_{task_dir.name}_"
    ) as fixed_tmp:
        buggy_dir = Path(buggy_tmp)
        fixed_dir = Path(fixed_tmp)
        prepare_buggy_workspace(task_dir, buggy_dir)
        prepare_fixed_workspace(task_dir, scrapy_root, fixed_dir)

        buggy_visible = run_suite(validator.VISIBLE_TESTS, buggy_dir, f"{task_dir.name}_buggy_visible")
        buggy_hidden = run_suite(validator.HIDDEN_TESTS, buggy_dir, f"{task_dir.name}_buggy_hidden")
        fixed_visible = run_suite(validator.VISIBLE_TESTS, fixed_dir, f"{task_dir.name}_fixed_visible")
        fixed_hidden = run_suite(validator.HIDDEN_TESTS, fixed_dir, f"{task_dir.name}_fixed_hidden")

    failures: list[str] = []
    if not is_noop and not is_impossible:
        if buggy_hidden.fraction == 1.0:
            failures.append("buggy hidden tests all pass")
        if fixed_hidden.fraction < 1.0:
            failures.append("fixed hidden tests do not fully pass")
        if fixed_visible.fraction < 1.0:
            failures.append("fixed visible tests do not fully pass")
    elif is_noop:
        if fixed_visible.fraction < 1.0 or fixed_hidden.fraction < 1.0:
            failures.append("no-op task does not fully pass on clean workspace")

    return {
        "task_id": task_dir.name,
        "task_type": meta.get("task_type"),
        "buggy_visible": buggy_visible.fraction,
        "buggy_hidden": buggy_hidden.fraction,
        "fixed_visible": fixed_visible.fraction,
        "fixed_hidden": fixed_hidden.fraction,
        "failures": failures,
    }


def resolve_task_dirs(benchmark_dir: Path, explicit_ids: list[str]) -> list[Path]:
    tasks_root = benchmark_dir / "tasks"
    if explicit_ids:
        return [tasks_root / task_id for task_id in explicit_ids]

    benchmark_json = json.loads((benchmark_dir / "benchmark.json").read_text())
    return [benchmark_dir / rel_path for rel_path in benchmark_json["task_dirs"]]


def main() -> int:
    args = parse_args()
    task_dirs = resolve_task_dirs(args.benchmark_dir, args.task)
    summaries = [audit_task(task_dir, args.scrapy_root) for task_dir in task_dirs]

    failures = [summary for summary in summaries if summary["failures"]]
    print(json.dumps({"summaries": summaries, "failing_tasks": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
