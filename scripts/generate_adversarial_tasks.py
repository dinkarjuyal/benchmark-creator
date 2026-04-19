"""Generate adversarial confounding MC tasks and write them to the benchmark dir.

Usage:
    python3 scripts/generate_adversarial_tasks.py [--n N] [--family FAMILY] [--dry-run]

Options:
    --n N           Questions per family per seed rule (default: 2)
    --family NAME   Only run this family (default: all)
    --dry-run       Generate questions but do not write task dirs
    --api-key KEY   Anthropic API key (or set ANTHROPIC_API_KEY env var)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generators.adversarial_mc import FAMILIES, AdversarialMCGenerator
from scripts.task_writer_mc import write_mc_task

BENCHMARK_DIR = ROOT / "benchmarks" / "pandas_understanding"
TASKS_DIR = BENCHMARK_DIR / "tasks"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=2, help="Questions per family per seed")
    parser.add_argument("--family", help="Restrict to one family")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--api-key", help="Anthropic API key")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Set ANTHROPIC_API_KEY or pass --api-key")

    families = FAMILIES
    if args.family:
        families = [f for f in FAMILIES if f["name"] == args.family]
        if not families:
            sys.exit(f"Unknown family '{args.family}'. Options: {[f['name'] for f in FAMILIES]}")

    gen = AdversarialMCGenerator(api_key=api_key, verbose=True)
    candidates = gen.generate(families=families, n_per_family=args.n)

    if not candidates:
        print("No questions generated.")
        return

    if args.dry_run:
        print("\n--- DRY RUN: questions generated but not written ---")
        for c in candidates:
            print(f"  {c.task_id}  correct={c.correct_id}  family={c.family}")
            print(f"    rule_predicts (hard neg) = {c.metadata.get('rule_predicts', '?')!r}")
            print(f"    actual_output (correct)  = {c.metadata.get('actual_output', '?')!r}")
        return

    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    written: list[dict] = []

    for cand in candidates:
        task_dir = write_mc_task(cand, TASKS_DIR)
        written.append({
            "id": cand.task_id,
            "path": str(task_dir.relative_to(ROOT)),
            "family": cand.family,
            "difficulty": cand.difficulty,
            "is_hard_negative": cand.is_hard_negative,
            "correct_id": cand.correct_id,
        })
        print(f"  Wrote: {task_dir.relative_to(ROOT)}")

    # Merge with existing benchmark.json if present
    benchmark_json_path = BENCHMARK_DIR / "benchmark.json"
    existing: list[dict] = []
    if benchmark_json_path.exists():
        data = json.loads(benchmark_json_path.read_text())
        existing = data if isinstance(data, list) else data.get("tasks", [])

    # Deduplicate by id
    existing_ids = {t["id"] for t in existing}
    new_entries = [t for t in written if t["id"] not in existing_ids]
    all_tasks = existing + new_entries

    benchmark_json_path.write_text(json.dumps(all_tasks, indent=2) + "\n")

    print(f"\nAdded {len(new_entries)} adversarial tasks to benchmark.json")
    print(f"Total tasks in benchmark: {len(all_tasks)}")
    print(f"\nRun against haiku:")
    print(f"  python3 -m harness.run_tasks \\")
    print(f"    --benchmark pandas_understanding \\")
    print(f"    --agent mini_claude_haiku_4_5_mc \\")
    print(f"    --runtime local \\")
    print(f"    --task-ids {','.join(t['id'] for t in written)}")


if __name__ == "__main__":
    main()
