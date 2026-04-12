#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _step_status(context: dict, step_name: str) -> tuple[bool, str]:
    step = next((item for item in context["steps"] if item["step"] == step_name), None)
    if step is None:
        return False, f"{step_name} step did not run."
    if step["timed_out"]:
        return False, f"{step_name} step timed out."
    if step["exit_code"] != 0:
        return False, f"{step_name} step exited with {step['exit_code']}."
    return True, ""


def _run_test(run_dir: Path, nodeid: str) -> tuple[bool, str]:
    hidden_tests_dir = Path("/task/hidden_tests")
    completed = subprocess.run(
        ["pytest", nodeid, "-q"],
        cwd=run_dir,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join((str(run_dir), str(hidden_tests_dir)))},
    )
    return completed.returncode == 0, completed.stdout + "\n" + completed.stderr


def main() -> int:
    context = json.loads(Path("/artifacts/runtime_context.json").read_text())

    for step_name in ("setup", "agent"):
        ok, message = _step_status(context, step_name)
        if not ok:
            print(json.dumps({"score": 0.0, "passed": False, "message": message}))
            return 0

    run_dir = Path(context["container_run_dir"])
    tests = [
        (
            "/task/hidden_tests/test_pipeline_from_crawler_error_surface.py::test_pipeline_setup_error_is_not_suppressed",
            0.7,
        ),
        (
            "/task/hidden_tests/test_pipeline_from_crawler_error_surface.py::test_valid_pipeline_still_loads",
            0.15,
        ),
        (
            "/task/hidden_tests/test_pipeline_from_crawler_error_surface.py::test_none_return_from_from_crawler_still_raises_type_error",
            0.15,
        ),
    ]
    score = 0.0
    logs: list[str] = []
    results: dict[str, bool] = {}
    for nodeid, weight in tests:
        passed, output = _run_test(run_dir, nodeid)
        logs.append(f"$ pytest {nodeid} -q\n{output}\n")
        results[nodeid] = passed
        if passed:
            score += weight
    Path("/artifacts/pytest_output.txt").write_text("\n".join(logs))
    passed = score == 1.0
    print(
        json.dumps(
            {
                "score": score,
                "passed": passed,
                "message": (
                    "Weighted regression tests passed."
                    if passed
                    else "Weighted regression tests did not fully pass. See pytest_output.txt."
                ),
                "metrics": results,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
