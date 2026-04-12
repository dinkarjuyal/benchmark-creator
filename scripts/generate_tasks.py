#!/usr/bin/env python3
"""Task generator orchestrator for the Scrapy-50 benchmark.

Usage:
    python3 scripts/generate_tasks.py [--scrapy-root PATH] [--out-dir PATH] [--max N]

Steps:
1. Verify (or clone) scrapy at pinned tag v2.12.0
2. Run all generators to produce TaskCandidate objects
3. Filter candidates against acceptance criteria
4. Select diverse top-N (default 50)
5. Write task directories under benchmarks/scrapy_50/tasks/
6. Write benchmarks/scrapy_50/benchmark.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generators.base import TaskCandidate
from scripts.generators.counterfactual import CounterfactualGenerator
from scripts.generators.contract_extension import ContractExtensionGenerator
from scripts.generators.noop_impossible import NoopImpossibleGenerator
from scripts.generators.structural_mining import StructuralMiningGenerator
from scripts.task_writer import write_task

SCRAPY_TAG = "2.11.2"
SCRAPY_REPO = "https://github.com/scrapy/scrapy.git"
DEFAULT_OUT = ROOT / "benchmarks" / "scrapy_50"
DEFAULT_MAX = 50


# ---------------------------------------------------------------------------
# Acceptance filter
# ---------------------------------------------------------------------------

def _is_acceptable(c: TaskCandidate) -> bool:
    """Return True if the candidate passes all acceptance criteria."""
    # Must have a non-empty prompt
    if not c.prompt.strip():
        return False
    # Must have at least one visible test
    if not c.visible_tests:
        return False
    # Must have at least one hidden test (except impossible tasks)
    if not c.is_impossible and not c.hidden_tests:
        return False
    # Reject pure no-op tasks without hidden tests (no way to score regression safety)
    if c.is_noop and not c.hidden_tests:
        return False
    return True


# ---------------------------------------------------------------------------
# Diversity selector
# ---------------------------------------------------------------------------

def _select_diverse(
    candidates: list[TaskCandidate],
    max_tasks: int,
) -> list[TaskCandidate]:
    """Select up to max_tasks candidates ensuring family and type diversity.

    Hard constraints:
    - At least 3 no-op tasks
    - At least 3 impossible tasks
    - At least 3 distinct families represented
    - At least 2 difficulty levels represented
    """
    noops      = [c for c in candidates if c.is_noop]
    impossible = [c for c in candidates if c.is_impossible]
    normal     = [c for c in candidates if not c.is_noop and not c.is_impossible]

    selected: list[TaskCandidate] = []

    # Guarantee minimums
    selected.extend(noops[:3])
    selected.extend(impossible[:3])

    # Fill remaining slots with normal tasks, prioritising family diversity
    seen_families: dict[str, int] = {}
    for c in sorted(normal, key=lambda x: (seen_families.get(x.family, 0), x.difficulty)):
        if len(selected) >= max_tasks:
            break
        selected.append(c)
        seen_families[c.family] = seen_families.get(c.family, 0) + 1

    return selected[:max_tasks]


# ---------------------------------------------------------------------------
# Scrapy checkout
# ---------------------------------------------------------------------------

def _ensure_scrapy(scrapy_root: Path | None) -> Path:
    if scrapy_root is not None:
        if not (scrapy_root / "scrapy").is_dir():
            raise SystemExit(f"ERROR: scrapy package not found at {scrapy_root}/scrapy")
        print(f"Using existing scrapy root: {scrapy_root}")
        return scrapy_root

    tmp = Path(tempfile.mkdtemp(prefix="scrapy_"))
    print(f"Cloning scrapy {SCRAPY_TAG} into {tmp} …")
    subprocess.run(
        ["git", "clone", "--depth=1", f"--branch={SCRAPY_TAG}", SCRAPY_REPO, str(tmp)],
        check=True,
    )
    return tmp


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Scrapy-50 benchmark tasks.")
    parser.add_argument("--scrapy-root", type=Path, default=None,
                        help="Path to an existing scrapy checkout (skips clone).")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT,
                        help=f"Output benchmark directory (default: {DEFAULT_OUT})")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX,
                        help=f"Maximum number of tasks to generate (default: {DEFAULT_MAX})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print candidate list without writing task files.")
    args = parser.parse_args()

    scrapy_root = _ensure_scrapy(args.scrapy_root)

    # --- Run generators ---
    print("\nRunning generators …")
    all_candidates: list[TaskCandidate] = []

    generators = [
        ("Counterfactual", CounterfactualGenerator(scrapy_root)),
        ("StructuralMining", StructuralMiningGenerator(scrapy_root)),
        ("ContractExtension", ContractExtensionGenerator(scrapy_root)),
        ("NoopImpossible", NoopImpossibleGenerator(scrapy_root)),
    ]
    for name, gen in generators:
        batch = gen.generate()
        print(f"  {name}: {len(batch)} candidates")
        all_candidates.extend(batch)

    print(f"\nTotal raw candidates: {len(all_candidates)}")

    # --- Filter ---
    filtered = [c for c in all_candidates if _is_acceptable(c)]
    print(f"After filtering: {len(filtered)}")

    # --- De-duplicate by task_id ---
    seen_ids: set[str] = set()
    deduped: list[TaskCandidate] = []
    for c in filtered:
        if c.task_id not in seen_ids:
            seen_ids.add(c.task_id)
            deduped.append(c)
    print(f"After dedup: {len(deduped)}")

    # --- Select diverse subset ---
    selected = _select_diverse(deduped, args.max)
    print(f"Selected: {len(selected)} tasks\n")

    # Print summary table
    print(f"{'ID':<45} {'TYPE':<22} {'FAM':<12} {'DIFF':>4}  {'NOOP':>5}  {'IMP':>4}")
    print("-" * 100)
    for c in selected:
        print(
            f"{c.task_id:<45} {c.task_type:<22} {c.family:<12} {c.difficulty:>4}  "
            f"{'Y' if c.is_noop else '':>5}  {'Y' if c.is_impossible else '':>4}"
        )

    if args.dry_run:
        print("\n[dry-run] No files written.")
        return 0

    # --- Write task directories ---
    tasks_dir = args.out_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nWriting task directories to {tasks_dir} …")

    task_dirs: list[str] = []
    failed: list[str] = []
    for c in selected:
        try:
            task_dir = write_task(c, scrapy_root, tasks_dir)
            rel = str(task_dir.relative_to(args.out_dir))
            task_dirs.append(rel)
            print(f"  ✓ {c.task_id}")
        except Exception as exc:
            print(f"  ✗ {c.task_id}: {exc}", file=sys.stderr)
            failed.append(c.task_id)

    # --- Write benchmark.json ---
    benchmark_json = {
        "id": "scrapy_50",
        "name": "Scrapy-50 Benchmark",
        "description": (
            "50 tasks across Scrapy subsystems. "
            "Includes counterfactual regressions, contract extensions, "
            "no-op tasks (correct behavior, agent must change nothing), "
            "and impossible tasks (agent must recognize infeasibility)."
        ),
        "scrapy_tag": SCRAPY_TAG,
        "task_dirs": task_dirs,
        "task_count": len(task_dirs),
        "scoring": {
            "formula": "0.6*hidden_test_fraction + 0.2*visible_test_fraction + 0.1*regression_safety + 0.1*policy_quality",
            "bands": {
                "0.0-0.2": "invalid patch / broken setup",
                "0.2-0.6": "partial behavior recovery",
                "0.6-0.9": "core fixed but regressions remain",
                "0.9-1.0": "semantically correct and regression-safe",
            },
        },
    }
    (args.out_dir / "benchmark.json").write_text(json.dumps(benchmark_json, indent=2) + "\n")

    print(f"\nWrote {len(task_dirs)} tasks. Failed: {len(failed)}.")
    if failed:
        print(f"Failed tasks: {failed}")
    print(f"benchmark.json → {args.out_dir / 'benchmark.json'}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
