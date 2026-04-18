"""Write an MCTaskCandidate to a harness-compatible task directory.

MC task layout (much simpler than Scrapy-50):
  <benchmark_dir>/tasks/<task_id>/
    task.json       — harness metadata
    prompt.txt      — the question shown to the agent
    public/
      setup.py      — no-op setup (just prints "ready")
    validator.py    — checks /work/answer.json against correct_id

No template/ directory: the agent doesn't get a code workspace.
The agent reads the question from prompt.txt and writes /work/answer.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.generators.pandas_mc import MCTaskCandidate
from scripts.verifier_builder_mc import build_mc_validator

IMAGE_NAME = "takehome-pandas-mc:py312-v1"
DOCKERFILE_REL = "../../docker/Dockerfile"
TIMEOUT_SEC = 120   # MC tasks need far less time than code tasks


def write_mc_task(
    candidate: MCTaskCandidate,
    benchmark_tasks_dir: Path,
) -> Path:
    """Write all task files and return the task directory path."""
    task_dir = benchmark_tasks_dir / candidate.task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # prompt.txt
    (task_dir / "prompt.txt").write_text(candidate.prompt + "\n")

    # public/setup.py  — no-op; just echoes ready
    public_dir = task_dir / "public"
    public_dir.mkdir(exist_ok=True)
    (public_dir / "setup.py").write_text(
        "#!/usr/bin/env python3\n"
        "# No workspace setup needed for MC tasks.\n"
        "print('Setup complete. Read /task/prompt.txt and write your answer to /work/answer.json.')\n"
    )

    # validator.py
    (task_dir / "validator.py").write_text(build_mc_validator(candidate))

    # task.json
    task_json = {
        "id": candidate.task_id,
        "description": candidate.description[:120],
        "image": IMAGE_NAME,
        "dockerfile": DOCKERFILE_REL,
        "timeout_sec": TIMEOUT_SEC,
        "prompt_file": "prompt.txt",
        "public_dir": "public",
        "setup_command": "python /task/public/setup.py",
        "validator_command": "python /task/validator.py",
        "_meta": {
            "task_type": candidate.question_type,
            "family": candidate.family,
            "difficulty": candidate.difficulty,
            "is_hard_negative": candidate.is_hard_negative,
            "correct_id": candidate.correct_id,
            "explanation": candidate.explanation,
            "curriculum_note": candidate.curriculum_note,
            "generation_recipe": candidate.metadata.get("generation_recipe", ""),
        },
    }
    (task_dir / "task.json").write_text(json.dumps(task_json, indent=2) + "\n")

    return task_dir
