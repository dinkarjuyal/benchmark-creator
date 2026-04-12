from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def run_scrapy(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "scrapy.cmdline", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        env=merged_env,
        check=False,
    )


def test_genspider_without_edit_still_creates_spider(tmp_path: Path):
    project_root = tmp_path / "workspace"
    result = run_scrapy("startproject", "demo", str(project_root), cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    project_dir = project_root
    result = run_scrapy("genspider", "example", "example.com", cwd=project_dir)
    assert result.returncode == 0, result.stderr
    assert (project_dir / "demo" / "spiders" / "example.py").exists()


def test_genspider_edit_uses_current_python_environment(tmp_path: Path):
    project_root = tmp_path / "workspace"
    result = run_scrapy("startproject", "demo", str(project_root), cwd=tmp_path)
    assert result.returncode == 0, result.stderr

    project_dir = project_root
    result = run_scrapy(
        "genspider",
        "--edit",
        "example",
        "example.com",
        cwd=project_dir,
        env={"EDITOR": "true"},
    )

    assert result.returncode == 0, result.stderr
    assert "not found" not in result.stderr
    assert "Spider not found" not in result.stderr
    assert (project_dir / "demo" / "spiders" / "example.py").exists()
