"""Write a TaskCandidate (coding diffusion) to a harness-compatible task directory.

Diffusion task layout:
  <benchmark_dir>/tasks/<task_id>/
    task.json       — harness metadata
    prompt.txt      — the debugging prompt shown to the agent
    public/
      setup.py      — applies corruption patches to the workspace
    validator.py    — runs visible + hidden tests, scores by pass rate

No template/ directory: the agent receives the corrupted source as the workspace
and must edit files in-place to fix the bugs.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.generators.base import TaskCandidate
from scripts.verifier_builder_diffusion import build_diffusion_validator

IMAGE_NAME = "takehome-pandas-mc:py312-v1"
DOCKERFILE_REL = "../../docker/Dockerfile"
TIMEOUT_SEC = 600  # Code-fixing tasks need more time than MC


def write_diffusion_task(
    candidate: TaskCandidate,
    benchmark_tasks_dir: Path,
) -> Path:
    """Write all task files for a coding diffusion task and return the task directory path."""
    task_dir = benchmark_tasks_dir / candidate.task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # prompt.txt
    (task_dir / "prompt.txt").write_text(candidate.prompt + "\n")

    # public/setup.py — applies corruption patches at runtime
    public_dir = task_dir / "public"
    public_dir.mkdir(exist_ok=True)
    _write_setup_py(public_dir, candidate)

    # validator.py
    (task_dir / "validator.py").write_text(build_diffusion_validator(candidate))

    # task.json
    corruptions = candidate.metadata.get("corruptions", [])
    schedule = candidate.metadata.get("schedule", {})

    task_json = {
        "id": candidate.task_id,
        "description": candidate.metadata.get("description", candidate.prompt.split("\n")[0][:120]),
        "image": IMAGE_NAME,
        "dockerfile": DOCKERFILE_REL,
        "timeout_sec": TIMEOUT_SEC,
        "prompt_file": "prompt.txt",
        "public_dir": "public",
        "setup_command": "python /task/public/setup.py",
        "validator_command": "python /task/validator.py",
        "_meta": {
            "task_type": candidate.task_type,
            "family": candidate.family,
            "difficulty": candidate.difficulty,
            "is_noop": candidate.is_noop,
            "is_impossible": candidate.is_impossible,
            "generation_recipe": candidate.generation_recipe,
            "n_corruptions": len(corruptions),
            "schedule": schedule,
            "corruption_files": list(dict.fromkeys(
                c["source_file"] for c in corruptions if "source_file" in c
            )),
        },
    }
    (task_dir / "task.json").write_text(json.dumps(task_json, indent=2) + "\n")

    return task_dir


def _write_setup_py(public_dir: Path, candidate: TaskCandidate) -> None:
    """Write a setup.py that applies corruption patches to the workspace at runtime.

    For coding diffusion tasks, the setup copies the library source into /work
    and then applies the corruption patches (find/replace operations) on top.
    """
    corruptions = candidate.metadata.get("corruptions", [])
    install = candidate.metadata.get("install", "")
    library_name = candidate.metadata.get("library_name", "")

    lines = [
        "#!/usr/bin/env python3",
        '"""Apply corruption patches to the workspace for coding diffusion task."""',
        "import os",
        "import subprocess",
        "import sys",
        "from pathlib import Path",
        "",
        "WORK = Path(os.environ.get('HARNESS_WORK_DIR', '/work'))",
        "",
    ]

    if install:
        lines.append(f"# Install the library")
        lines.append(f"print('Installing library...')")
        lines.append(f"subprocess.run({install.split()!r}, check=True, capture_output=True)")
        lines.append("")

    # Write corruption patches as find/replace operations
    # Group by source file
    file_corruptions: dict[str, list[dict]] = {}
    for c in corruptions:
        sf = c.get("source_file", "")
        if sf:
            file_corruptions.setdefault(sf, []).append(c)

    if file_corruptions:
        lines.append("# Apply corruption patches (find/replace)")
        lines.append("print('Applying corruption patches...')")
        lines.append("")

        for source_file, corrupts in file_corruptions.items():
            lines.append(f"# Corruptions in {source_file}")
            # Read the clean source file
            lines.append(f"_path_{_safe_var(source_file)} = WORK / {source_file!r}")
            lines.append(f"if _path_{_safe_var(source_file)}.exists():")
            lines.append(f"    _content_{_safe_var(source_file)} = _path_{_safe_var(source_file)}.read_text()")

            for i, c in enumerate(corrupts):
                find_str = c.get("find", "")
                replace_str = c.get("replace", "")
                if find_str and replace_str:
                    lines.append(f"    # Corruption {i+1}: {c.get('description', '')[:60]}")
                    lines.append(f"    _content_{_safe_var(source_file)} = _content_{_safe_var(source_file)}.replace(")
                    lines.append(f"        {find_str!r},")
                    lines.append(f"        {replace_str!r},")
                    lines.append(f"        1  # Replace only first occurrence")
                    lines.append(f"    )")

            lines.append(f"    _path_{_safe_var(source_file)}.write_text(_content_{_safe_var(source_file)})")
            lines.append("")

    else:
        # No specific corruptions — minimal setup
        lines.append("# No specific corruption patches for this task")
        lines.append("# The workspace should already have the corrupted codebase")
        lines.append("")

    # Write visible tests into the workspace
    visible_tests = candidate.visible_tests
    if visible_tests:
        lines.append("# Write visible test files")
        for i, test_code in enumerate(visible_tests):
            lines.append(f"(WORK / 'test_visible_{candidate.task_id}_{i}.py').write_text({test_code!r})")
        lines.append("")

    lines.append("print('Setup complete: corruption patches applied.')")
    (public_dir / "setup.py").write_text("\n".join(lines) + "\n")


def _safe_var(path: str) -> str:
    """Convert a file path to a safe Python variable name."""
    return (
        path.replace("/", "_")
        .replace(".", "_")
        .replace("-", "_")
        .replace(" ", "_")
        .strip("_")
    )
