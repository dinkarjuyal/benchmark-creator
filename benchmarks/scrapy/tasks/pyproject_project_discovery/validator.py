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


def main() -> int:
    context = json.loads(Path("/artifacts/runtime_context.json").read_text())

    for step_name in ("setup", "agent"):
        ok, message = _step_status(context, step_name)
        if not ok:
            print(json.dumps({"score": 0.0, "passed": False, "message": message}))
            return 0

    run_dir = Path(context["container_run_dir"])
    hidden_tests_dir = Path("/task/hidden_tests")
    completed = subprocess.run(
        ["pytest", str(hidden_tests_dir / "test_pyproject_project_discovery.py"), "-q"],
        cwd=run_dir,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join((str(run_dir), str(hidden_tests_dir)))},
    )

    Path("/artifacts/pytest_stdout.txt").write_text(completed.stdout)
    Path("/artifacts/pytest_stderr.txt").write_text(completed.stderr)

    passed = completed.returncode == 0
    print(
        json.dumps(
            {
                "score": 1.0 if passed else 0.0,
                "passed": passed,
                "message": (
                    "Regression tests passed."
                    if passed
                    else "Regression tests failed. See pytest_stdout.txt and pytest_stderr.txt."
                ),
                "metrics": {"pytest_exit_code": completed.returncode},
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
