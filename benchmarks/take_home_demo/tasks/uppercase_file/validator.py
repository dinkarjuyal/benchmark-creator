#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    context = json.loads(Path("/artifacts/runtime_context.json").read_text())
    run_dir = Path(context["container_run_dir"])
    output_path = run_dir / "output.txt"
    expected = "LIGHTWEIGHT HARNESS"
    agent_step = next((step for step in context["steps"] if step["step"] == "agent"), None)

    if agent_step is None:
        result = {
            "score": 0.0,
            "passed": False,
            "message": "Agent step did not run.",
            "metrics": {"agent_step_present": False},
        }
    elif agent_step["timed_out"]:
        result = {
            "score": 0.0,
            "passed": False,
            "message": "Agent command timed out.",
            "metrics": {"agent_step_present": True},
        }
    elif agent_step["exit_code"] != 0:
        result = {
            "score": 0.0,
            "passed": False,
            "message": f"Agent command exited with {agent_step['exit_code']}.",
            "metrics": {"agent_step_present": True},
        }
    elif not output_path.exists():
        result = {
            "score": 0.0,
            "passed": False,
            "message": "output.txt was not created.",
            "metrics": {"agent_step_present": True},
        }
    else:
        actual = output_path.read_text().strip()
        passed = actual == expected
        result = {
            "score": 1.0 if passed else 0.0,
            "passed": passed,
            "message": "Output matched expected contents." if passed else f"Unexpected output: {actual!r}",
            "metrics": {
                "agent_step_present": True,
                "output_exists": True,
            },
        }

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
