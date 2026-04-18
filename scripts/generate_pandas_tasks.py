#!/usr/bin/env python3
"""Generate the pandas-understanding MC benchmark.

Usage:
    python3 scripts/generate_pandas_tasks.py [--out-dir PATH]

Outputs:
    benchmarks/pandas_understanding/tasks/<task_id>/  (one dir per question)
    benchmarks/pandas_understanding/benchmark.json    (task registry)

No external dependencies beyond pandas_injections.py entries.
The questions are self-contained (source excerpts are embedded in each entry).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generators.pandas_mc import PandasMCGenerator
from scripts.task_writer_mc import write_mc_task


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate pandas-understanding MC benchmark tasks."
    )
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "benchmarks" / "pandas_understanding"),
        help="Output benchmark directory.",
    )
    parser.add_argument(
        "--shuffle-seed",
        type=int,
        default=42,
        help="Random seed for choice order shuffling.",
    )
    parser.add_argument(
        "--min-difficulty",
        type=int,
        default=1,
        help="Only include tasks at this difficulty level or above.",
    )
    parser.add_argument(
        "--max-difficulty",
        type=int,
        default=5,
        help="Only include tasks at this difficulty level or below.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    tasks_dir = out_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    generator = PandasMCGenerator(shuffle_seed=args.shuffle_seed)
    candidates = generator.generate()

    # Filter by difficulty
    candidates = [
        c for c in candidates
        if args.min_difficulty <= c.difficulty <= args.max_difficulty
    ]

    if not candidates:
        print("No candidates after filtering.", file=sys.stderr)
        return 2

    print(f"Generating {len(candidates)} MC tasks → {tasks_dir}")

    task_dirs_rel: list[str] = []
    by_family: dict[str, int] = {}
    by_difficulty: dict[int, int] = {}
    hard_negative_count = 0

    for cand in candidates:
        task_dir = write_mc_task(cand, tasks_dir)
        rel = task_dir.relative_to(out_dir).as_posix()
        task_dirs_rel.append(f"tasks/{cand.task_id}")
        by_family[cand.family] = by_family.get(cand.family, 0) + 1
        by_difficulty[cand.difficulty] = by_difficulty.get(cand.difficulty, 0) + 1
        if cand.is_hard_negative:
            hard_negative_count += 1
        print(f"  [{cand.difficulty}] {cand.task_id}  ({'HARD NEG' if cand.is_hard_negative else cand.family})")

    # Write benchmark.json
    benchmark_json = {
        "name": "pandas-understanding",
        "description": (
            "Counterfactual curriculum benchmark for pandas code understanding. "
            "Each task is a multiple-choice question: given a proposed change to pandas internals, "
            "predict the output of a short snippet. Tests causal reasoning, not code generation."
        ),
        "version": "1.0",
        "task_dirs": task_dirs_rel,
        "stats": {
            "total_tasks": len(candidates),
            "hard_negatives": hard_negative_count,
            "by_family": by_family,
            "by_difficulty": by_difficulty,
        },
        "scoring": {
            "formula": "score = 1.0 if correct and clean_workspace else 0.8 if correct else 0.0",
            "correct": "agent chose the right answer (matched correct_id in validator)",
            "clean_workspace": "agent only wrote /work/answer.json, no other file edits",
            "curriculum_levels": {
                "1": "single function, local semantics",
                "2": "cross-type or cross-parameter reasoning",
                "3": "cross-function or non-local effect",
                "4": "transform-level cascade or emergent behavior",
                "5": "hard negatives, false positives",
            },
        },
    }
    (out_dir / "benchmark.json").write_text(json.dumps(benchmark_json, indent=2) + "\n")
    print(f"\nbenchmark.json written → {out_dir / 'benchmark.json'}")
    print(f"Tasks by family:     {by_family}")
    print(f"Tasks by difficulty: {dict(sorted(by_difficulty.items()))}")
    print(f"Hard negatives:      {hard_negative_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
