"""Offline T_fail discovery: for each corruption in the catalog, find which
pytest tests transition pass->fail. Cached on disk so the expensive run is
amortized across all evaluation runs.

Usage:
    python discover_tfail.py --catalog hand --domain sklearn
    python discover_tfail.py --catalog all --workers 8

The cache lives at $CDBENCH_TFAIL_CACHE (default /mnt/localssd/cdbench/tfail_cache).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.functional_judge import (
    SANDBOX_ROOT,
    TFAIL_CACHE,
    discover_tfail,
    ensure_sandbox,
)


# Source file -> pytest target mapping. Narrows discovery to the relevant
# test module so we don't run the entire 30K-test sklearn suite per corruption.
SOURCE_TO_TESTS = {
    "sklearn/metrics/_classification.py": ["sklearn/metrics/tests/test_classification.py"],
    "sklearn/metrics/_ranking.py": ["sklearn/metrics/tests/test_ranking.py"],
    "sklearn/preprocessing/_data.py": ["sklearn/preprocessing/tests/test_data.py"],
    "sklearn/linear_model/_ridge.py": ["sklearn/linear_model/tests/test_ridge.py"],
    "sklearn/ensemble/_forest.py": ["sklearn/ensemble/tests/test_forest.py"],
    "sklearn/model_selection/_split.py": ["sklearn/model_selection/tests/test_split.py"],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="sklearn")
    ap.add_argument("--catalog", choices=["hand", "sgs", "all"], default="hand")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore cache, re-run discovery")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    # Ensure sandbox is set up
    if args.domain == "sklearn":
        sandbox = ensure_sandbox(
            "sklearn",
            "https://github.com/scikit-learn/scikit-learn.git",
            commit="1.6.0",
            pip_extra=["pytest", "pytest-timeout", "pytest-xdist"],
        )
    else:
        raise SystemExit(f"unknown domain: {args.domain}")

    # Load corruption catalog
    from scripts.benchmark_ablation import HAND_CORRUPTIONS
    if args.catalog == "hand":
        corruptions = list(HAND_CORRUPTIONS)
    elif args.catalog == "sgs":
        # SGS corruptions are model-generated; load from a saved JSON
        sgs_path = ROOT / "results" / "sgs_corruptions.json"
        if not sgs_path.exists():
            raise SystemExit(f"no SGS catalog at {sgs_path}; generate one first")
        from scripts.generators.coding_diffusion import CorruptionSpec
        corruptions = [CorruptionSpec(**c) for c in json.loads(sgs_path.read_text())]
    else:
        from scripts.generators.coding_diffusion import CorruptionSpec
        sgs_path = ROOT / "results" / "sgs_corruptions.json"
        sgs = []
        if sgs_path.exists():
            sgs = [CorruptionSpec(**c) for c in json.loads(sgs_path.read_text())]
        corruptions = list(HAND_CORRUPTIONS) + sgs

    if args.limit:
        corruptions = corruptions[: args.limit]

    print(f"Discovering T_fail for {len(corruptions)} corruptions in {sandbox}")
    TFAIL_CACHE.mkdir(parents=True, exist_ok=True)

    summary = []
    start = time.time()
    for i, c in enumerate(corruptions, 1):
        targets = SOURCE_TO_TESTS.get(c.source_file)
        if not targets:
            print(f"  [{i}/{len(corruptions)}] {c.corruption_id}: no test mapping; SKIP")
            summary.append({"corruption_id": c.corruption_id, "tfail": [], "skipped": True})
            continue
        t0 = time.time()
        try:
            tfail = discover_tfail(c, sandbox, test_targets=targets, refresh=args.refresh)
        except Exception as e:
            print(f"  [{i}/{len(corruptions)}] {c.corruption_id}: ERROR {e}")
            summary.append({"corruption_id": c.corruption_id, "tfail": [], "error": str(e)})
            continue
        dt = time.time() - t0
        print(f"  [{i}/{len(corruptions)}] {c.corruption_id}: {len(tfail)} tests fail "
              f"({dt:.1f}s)")
        summary.append({"corruption_id": c.corruption_id, "tfail": tfail, "elapsed_sec": dt})

    total = time.time() - start
    out = ROOT / "results" / f"tfail_summary_{args.domain}_{args.catalog}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "domain": args.domain,
        "catalog": args.catalog,
        "total_elapsed_sec": total,
        "corruptions": summary,
    }, indent=2))
    print(f"\nDone in {total:.1f}s. Summary: {out}")
    print(f"Cache: {TFAIL_CACHE}")


if __name__ == "__main__":
    main()
