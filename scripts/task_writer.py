"""Write a TaskCandidate to a harness-compatible task directory.

Task directory layout produced:
  <benchmark_dir>/tasks/<task_id>/
    task.json
    prompt.txt
    public/
      setup.py       ← applies start_state_patches to the workspace
    template/        ← full scrapy checkout with patches applied + test files
      scrapy/        ← patched scrapy source
      tests/         ← visible test files (agent can run these)
    validator.py     ← scoring logic (private; only validator step sees this)
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from scripts.generators.base import TaskCandidate
from scripts.verifier_builder import build_validator

IMAGE_NAME = "takehome-scrapy-mini:py312-v2"
DOCKERFILE_REL = "../../docker/Dockerfile"
TIMEOUT_SEC = 300


def write_task(
    candidate: TaskCandidate,
    scrapy_root: Path,
    benchmark_tasks_dir: Path,
) -> Path:
    """Write all task files and return the task directory path."""
    task_dir = benchmark_tasks_dir / candidate.task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # prompt.txt
    # ------------------------------------------------------------------
    (task_dir / "prompt.txt").write_text(candidate.prompt + "\n")

    # ------------------------------------------------------------------
    # public/setup.py  — applies start_state_patches at runtime
    # ------------------------------------------------------------------
    public_dir = task_dir / "public"
    public_dir.mkdir(exist_ok=True)
    _write_setup_py(public_dir, candidate.start_state_patches)

    # ------------------------------------------------------------------
    # template/  — scrapy checkout + visible tests
    # ------------------------------------------------------------------
    template_dir = task_dir / "template"
    if template_dir.exists():
        shutil.rmtree(template_dir)
    _write_template(template_dir, scrapy_root, candidate)
    _write_baseline_manifest(public_dir, template_dir)

    # ------------------------------------------------------------------
    # validator.py
    # ------------------------------------------------------------------
    (task_dir / "validator.py").write_text(build_validator(candidate))

    # ------------------------------------------------------------------
    # task.json
    # ------------------------------------------------------------------
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
        "template_dir": "template",
        "_meta": {
            "task_type": candidate.task_type,
            "family": candidate.family,
            "difficulty": candidate.difficulty,
            "is_noop": candidate.is_noop,
            "is_impossible": candidate.is_impossible,
            "generation_recipe": candidate.generation_recipe,
        },
    }
    (task_dir / "task.json").write_text(json.dumps(task_json, indent=2) + "\n")

    return task_dir


_MINI_DETERMINISTIC_YAML = """\
model:
  outputs:
    - role: assistant
      content: "I will read the prompt and attempt the task."
      extra:
        cost: 0.0
        actions:
          - command: "cat /task/prompt.txt"
    - role: assistant
      content: "Task complete."
      extra:
        cost: 0.0
        actions:
          - command: "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
"""


def _write_setup_py(public_dir: Path, patches: dict[str, str]) -> None:
    """Write a setup.py that applies file patches to /work at runtime."""
    if not patches:
        # No patches — setup.py is a no-op
        (public_dir / "setup.py").write_text(
            "# No patches needed for this task — workspace is used as-is.\n"
            "print('Setup complete (no patches).')\n"
        )
        (public_dir / "mini_deterministic.yaml").write_text(_MINI_DETERMINISTIC_YAML)
        return

    lines = [
        "#!/usr/bin/env python3",
        '"""Apply start-state patches to the workspace."""',
        "import os",
        "from pathlib import Path",
        "",
        "WORK = Path(os.environ.get('HARNESS_WORK_DIR', '/work'))",
        "",
    ]
    for rel_path, content in patches.items():
        var_name = rel_path.replace("/", "_").replace(".", "_")
        lines.append(f"# Patch: {rel_path}")
        lines.append(f"_content_{var_name} = {content!r}")
        lines.append(f"(WORK / {rel_path!r}).write_text(_content_{var_name})")
        lines.append("")

    lines.append("print('Setup complete: patches applied.')")
    (public_dir / "setup.py").write_text("\n".join(lines) + "\n")
    (public_dir / "mini_deterministic.yaml").write_text(_MINI_DETERMINISTIC_YAML)


def _write_template(
    template_dir: Path,
    scrapy_root: Path,
    candidate: TaskCandidate,
) -> None:
    """Copy scrapy source into template/, apply patches, add visible test files."""
    template_dir.mkdir(parents=True)

    # Copy scrapy package source
    scrapy_src = scrapy_root / "scrapy"
    scrapy_dst = template_dir / "scrapy"
    shutil.copytree(scrapy_src, scrapy_dst)

    # Copy key top-level project files needed by tests
    for fname in ("pyproject.toml", "setup.py", "setup.cfg", "README.rst"):
        src = scrapy_root / fname
        if src.exists():
            shutil.copy2(src, template_dir / fname)

    # Copy tests directory (needed for regression safety checks)
    tests_src = scrapy_root / "tests"
    if tests_src.exists():
        tests_dst = template_dir / "tests"
        shutil.copytree(tests_src, tests_dst)

    # Apply start_state_patches (mutations) on top of the copied source
    for rel_path, patched_content in candidate.start_state_patches.items():
        target = template_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(patched_content)

    # Write visible test file(s) into template/tests/
    vis_tests_dir = template_dir / "tests"
    vis_tests_dir.mkdir(exist_ok=True)
    for i, test_code in enumerate(candidate.visible_tests):
        (vis_tests_dir / f"test_visible_{candidate.task_id}_{i}.py").write_text(test_code)

    # Write any extra template files (e.g. conftest, fixtures)
    for rel_path, content in candidate.extra_template_files.items():
        target = template_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def _write_baseline_manifest(public_dir: Path, template_dir: Path) -> None:
    """Write a hash manifest for workspace files used by validator diff checks."""
    manifest: dict[str, dict[str, int | str]] = {}
    for prefix in ("scrapy",):
        base = template_dir / prefix
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel_path = path.relative_to(template_dir).as_posix()
            raw = path.read_bytes()
            manifest[rel_path] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }

    (public_dir / "baseline_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
