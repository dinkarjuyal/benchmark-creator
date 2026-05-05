#!/usr/bin/env python3
"""Quick test: benchmark 1 difficulty level on PI to verify the full pipeline."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generators.coding_diffusion import _make_client, CorruptionSpec

client = _make_client(None, provider="prime")

ORIGINAL = """\
import math
from typing import List, Optional

def weighted_average(values: List[float], weights: List[float]) -> float:
    if len(values) != len(weights):
        raise ValueError("Length mismatch")
    total = 0.0
    for i in range(len(values)):
        total += values[i] * weights[i]
    return total / sum(weights)

def clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value

def is_in_range(value: float, lo: float, hi: float) -> bool:
    return value >= lo and value <= hi

def safe_sqrt(x: float) -> Optional[float]:
    if x < 0:
        return None
    return math.sqrt(x)

def normalize_to_unit(values: List[float]) -> List[float]:
    if not values:
        return []
    max_val = max(values)
    if max_val == 0:
        return values
    return [v / max_val for v in values]

def percentile_rank(values: List[float], target: float) -> float:
    if not values:
        return 0.0
    below = sum(1 for v in values if v < target)
    return below / len(values)

def batch_process(items: List[float], threshold: float) -> List[float]:
    result = []
    for i in range(len(items)):
        if items[i] > threshold:
            result.append(items[i] * 2)
        else:
            result.append(items[i])
    return result
"""

TEST_CODE = """\
import sys
sys.path.insert(0, "SRC_DIR")
from math_utils import *

def test_weighted_average():
    assert weighted_average([1, 2, 3], [1, 1, 1]) == 2.0

def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0

def test_is_in_range():
    assert is_in_range(5, 0, 10) == True
    assert is_in_range(0, 0, 10) == True

def test_safe_sqrt():
    assert safe_sqrt(4) == 2.0
    assert safe_sqrt(-1) is None

def test_normalize():
    assert normalize_to_unit([2, 4, 6]) == [1/3, 2/3, 1.0]

def test_percentile():
    assert percentile_rank([1, 2, 3, 4, 5], 3) == 0.4

def test_batch():
    assert batch_process([1, 5, 3, 7], 4) == [1, 10, 3, 14]
"""

# Test each difficulty level
MANUAL_CORRUPTIONS = [
    ("if x < 0:", "if x > 0:", "safe_sqrt: condition inverted"),
    ("if value < lo:", "if value > lo:", "clamp: condition inverted"),
    ("return value >= lo and value <= hi", "return value > lo and value < hi", "is_in_range: boundary exclusion"),
    ("if items[i] > threshold:", "if items[i] >= threshold:", "batch_process: off-by-one threshold"),
    ("below = sum(1 for v in values if v < target)", "below = sum(1 for v in values if v <= target)", "percentile_rank: off-by-one"),
]

def apply_corruptions(code, n_bugs):
    corrupted = code
    applied = []
    for find, replace, desc in MANUAL_CORRUPTIONS[:n_bugs]:
        if find in corrupted:
            corrupted = corrupted.replace(find, replace, 1)
            applied.append(desc)
    return corrupted, applied

def build_prompt(corrupted, n_bugs, descs):
    return (
        f"You are a debugging agent. The following Python code has {n_bugs} bug(s) introduced by a recent refactor.\n"
        f"Your task: find and fix ALL {n_bugs} bug(s) so that all tests pass.\n\n"
        f"Rules:\n"
        f"- Each bug is a single-point change (logic inversion, off-by-one, wrong comparison)\n"
        f"- Fix ONLY the bugs — do not refactor or add new features\n"
        f"- Return the COMPLETE fixed code in a single code block\n\n"
        f"Here is the corrupted code:\n\n"
        f"```python\n{corrupted}\n```\n\n"
        f"Here are the tests your fix must pass:\n\n"
        f"```python\n{TEST_CODE}\n```\n\n"
        f"Return the COMPLETE fixed code in a single ```python block."
    )

def extract_code(response):
    # Try ```python first (most specific), then generic ```
    for marker in ["```python", "```Python"]:
        if marker in response:
            code = response.split(marker, 1)[1].split("```", 1)[0].strip()
            if len(code) > 50:
                return code
    # Fallback: generic ```
    if "```" in response:
        code = response.split("```", 1)[1].split("```", 1)[0].strip()
        if code.startswith("python"):
            code = code[len("python"):].strip()
        if len(code) > 50:
            return code
    return response

def score_fix(fixed_code, corruptions_applied):
    with tempfile.TemporaryDirectory() as tmpdir:
        # Put module directly in tmpdir so 'from math_utils import *' works
        (Path(tmpdir) / "math_utils.py").write_text(fixed_code)

        test_content = TEST_CODE.replace("SRC_DIR", tmpdir)
        (Path(tmpdir) / "test_math_utils.py").write_text(test_content)

        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(Path(tmpdir) / "test_math_utils.py"),
             "-v", "--tb=short", "-o", "addopts="],
            capture_output=True, text=True, timeout=30, cwd=tmpdir,
        )
        passed = result.stdout.count("PASSED")
        failed = result.stdout.count("FAILED")
        total = max(passed + failed, 1)

        # Count bugs fixed (check that original find string is back)
        bugs_fixed = 0
        for find, replace, desc in corruptions_applied:
            if find in fixed_code:
                bugs_fixed += 1

        return {
            "score": round(passed / total, 4),
            "tests_passed": passed,
            "tests_total": total,
            "bugs_fixed": bugs_fixed,
            "bugs_total": len(corruptions_applied),
        }

def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen/qwen3-8b"
    print(f"Benchmark: {model}")
    print(f"Corruptions available: {len(MANUAL_CORRUPTIONS)}")
    print()

    results = []
    for n_bugs in [1, 2, 3, 4, 5]:
        corrupted, applied = apply_corruptions(ORIGINAL, n_bugs)
        prompt = build_prompt(corrupted, n_bugs, applied)

        print(f"--- Difficulty {n_bugs} ({len(applied)} bugs) ---")
        for d in applied:
            print(f"  - {d}")

        print(f"  Calling {model}...", end="", flush=True)
        start = time.time()
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=4096,
                system="You are an expert Python debugging agent. Find and fix bugs. Return the complete fixed code in a single code block.",
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text if hasattr(resp, "content") else str(resp)
        except Exception as e:
            print(f" ERROR: {e}")
            results.append({"difficulty": n_bugs, "score": 0.0, "error": str(e)})
            continue
        elapsed = time.time() - start
        print(f" {elapsed:.1f}s ({len(text)} chars)")

        fixed_code = extract_code(text)
        scoring = score_fix(fixed_code, MANUAL_CORRUPTIONS[:n_bugs])
        print(f"  Score: {scoring['score']:.0%} | Tests: {scoring['tests_passed']}/{scoring['tests_total']} | Bugs fixed: {scoring['bugs_fixed']}/{scoring['bugs_total']}")

        results.append({
            "difficulty": n_bugs,
            "elapsed_sec": round(elapsed, 1),
            **scoring,
        })

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  {'Diff':>4} {'Score':>6} {'Tests':>8} {'Bugs':>8} {'Time':>6}")
    print(f"  {'─'*4} {'─'*6} {'─'*8} {'─'*8} {'─'*6}")
    for r in results:
        s = r.get("score", 0)
        t = f"{r.get('tests_passed','?')}/{r.get('tests_total','?')}"
        b = f"{r.get('bugs_fixed','?')}/{r.get('bugs_total','?')}"
        e = f"{r.get('elapsed_sec','?')}s"
        print(f"  {r['difficulty']:>4} {s:>6.0%} {t:>8} {b:>8} {e:>6}")

    # Save
    out = ROOT / "results" / "diffusion_benchmark.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": model, "results": results}, indent=2))
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
