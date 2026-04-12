#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def main() -> int:
    prompt = Path("/task/prompt.txt").read_text().strip()
    Path("/artifacts/task_prompt_snapshot.txt").write_text(prompt + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
