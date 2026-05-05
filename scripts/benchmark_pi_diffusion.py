#!/usr/bin/env python3
"""Benchmark a Prime Intellect model on coding diffusion tasks.

Generates code-fixing tasks with increasing difficulty (1-5 corruptions),
sends them to a PI model, and scores the results.

Usage:
    python3 scripts/benchmark_pi_diffusion.py
    MODEL=qwen/qwen3-8b python3 scripts/benchmark_pi_diffusion.py
    MODEL=qwen/qwen3-30b-a3b python3 scripts/benchmark_pi_diffusion.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generators.coding_diffusion import (
    CorruptionSpec,
    DiffusionSchedule,
    CodingDiffusionGenerator,
    _generate_pattern_corruptions,
    _make_client,
    _run_snippet,
)
from scripts.generators.bug_patterns import inject_bugs

# ── Config ─────────────────────────────────────────────────────────────────────

PROVIDER = os.environ.get("PROVIDER", "prime")
MODEL = os.environ.get("MODEL", "qwen/qwen3-8b")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))
VERBOSE = os.environ.get("VERBOSE", "1") == "1"

# Manual corruptions that are guaranteed to be detectable (used as primary source
# since pattern-based generation can't always produce visible bugs for all code)
MANUAL_CORRUPTIONS = [
    CorruptionSpec(
        corruption_id="corr_manual_loop_skip",
        source_file="src/math_utils.py",
        find="for i in range(len(values)):",
        replace="for i in range(len(values) - 1):",
        description="Off-by-one: loop skips last element in weighted_average",
        broken_test="assert weighted_average([1,2,3], [1,1,1]) == 2.0",
        passing_test="",
        family="math_utils",
        subtlety=2,
    ),
    CorruptionSpec(
        corruption_id="corr_manual_boundary_clamp",
        source_file="src/math_utils.py",
        find="if value < lo:",
        replace="if value > lo:",
        description="Condition inverted: < changed to > in clamp",
        broken_test="assert clamp(-1, 0, 10) == 0",
        passing_test="",
        family="math_utils",
        subtlety=2,
    ),
    CorruptionSpec(
        corruption_id="corr_manual_boundary_range",
        source_file="src/math_utils.py",
        find="return value >= lo and value <= hi",
        replace="return value > lo and value < hi",
        description="Boundary exclusion: >= changed to >, <= changed to <",
        broken_test="assert is_in_range(0, 0, 10) == True",
        passing_test="",
        family="math_utils",
        subtlety=2,
    ),
    CorruptionSpec(
        corruption_id="corr_manual_sqrt_cond",
        source_file="src/math_utils.py",
        find="if x < 0:",
        replace="if x > 0:",
        description="Condition inverted: < changed to > in safe_sqrt",
        broken_test="assert safe_sqrt(-1) is None",
        passing_test="",
        family="math_utils",
        subtlety=2,
    ),
    CorruptionSpec(
        corruption_id="corr_manual_batch_thresh",
        source_file="src/math_utils.py",
        find="if items[i] > threshold:",
        replace="if items[i] >= threshold:",
        description="Off-by-one: > changed to >= in batch_process threshold",
        broken_test="assert batch_process([4], 4) == [4]",
        passing_test="",
        family="math_utils",
        subtlety=2,
    ),
    CorruptionSpec(
        corruption_id="corr_manual_pct_below",
        source_file="src/math_utils.py",
        find="below = sum(1 for v in values if v < target)",
        replace="below = sum(1 for v in values if v <= target)",
        description="Off-by-one: < changed to <= in percentile_rank",
        broken_test="assert percentile_rank([1,2,3,4,5], 3) == 0.4",
        passing_test="",
        family="math_utils",
        subtlety=3,
    ),
    CorruptionSpec(
        corruption_id="corr_manual_norm_zero",
        source_file="src/math_utils.py",
        find="if max_val == 0:",
        replace="if max_val != 0:",
        description="Condition inverted: == changed to != in normalize_to_unit",
        broken_test="assert normalize_to_unit([0, 0]) == [0, 0]",
        passing_test="",
        family="math_utils",
        subtlety=3,
    ),
]

# Code we'll corrupt — a small but realistic module
BASE_CODE = {
    "src/math_utils.py": """\
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
""",
}

# Test code that the model should make pass
TEST_CODE = """\
import sys
sys.path.insert(0, '/tmp/workspace/src')
from math_utils import *

# Test weighted_average
def test_weighted_average():
    assert weighted_average([1, 2, 3], [1, 1, 1]) == 2.0
    assert abs(weighted_average([1, 2, 3], [0.5, 0.3, 0.2]) - 1.625) < 1e-9
    try:
        weighted_average([1, 2], [1])
        assert False, "Should raise ValueError"
    except ValueError:
        pass

# Test clamp
def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(15, 0, 10) == 10

# Test is_in_range
def test_is_in_range():
    assert is_in_range(5, 0, 10) == True
    assert is_in_range(0, 0, 10) == True
    assert is_in_range(10, 0, 10) == True
    assert is_in_range(-1, 0, 10) == False
    assert is_in_range(11, 0, 10) == False

# Test safe_sqrt
def test_safe_sqrt():
    assert safe_sqrt(4) == 2.0
    assert safe_sqrt(0) == 0.0
    assert safe_sqrt(-1) is None

# Test normalize_to_unit
def test_normalize_to_unit():
    assert normalize_to_unit([2, 4, 6]) == [1/3, 2/3, 1.0]
    assert normalize_to_unit([]) == []
    assert normalize_to_unit([0, 0]) == [0, 0]

# Test percentile_rank
def test_percentile_rank():
    assert percentile_rank([1, 2, 3, 4, 5], 3) == 0.4
    assert percentile_rank([], 5) == 0.0

# Test batch_process
def test_batch_process():
    assert batch_process([1, 5, 3, 7], 4) == [1, 10, 3, 14]
    assert batch_process([], 5) == []
"""


def apply_corruptions(code: str, corruptions: list[CorruptionSpec]) -> str:
    """Apply find/replace corruption patches to code."""
    result = code
    for c in corruptions:
        result = result.replace(c.find, c.replace, 1)
    return result


def build_model_prompt(corrupted_code: str, n_bugs: int, affected_files: list[str]) -> str:
    """Build the prompt sent to the model."""
    return f"""You are a debugging agent. The following Python code has {n_bugs} bug(s) introduced by a recent refactor.

Your task: find and fix ALL {n_bugs} bug(s) so that all tests pass.

Rules:
- Each bug is a single-point change (logic inversion, off-by-one, missing check, wrong variable, swapped operator, etc.)
- No functions were deleted or added — only existing logic was changed
- Fix ONLY the bugs — do not refactor or add new features
- Return the COMPLETE fixed code for each affected file

Affected files: {', '.join(affected_files)}

Here is the corrupted code:

```python
{corrupted_code}
```

Here are the tests your fix must pass:

```python
{TEST_CODE}
```

Return the fixed code for each file, wrapped in ```python ... ``` blocks.
"""


def extract_fixed_code(response: str, filename: str) -> str | None:
    """Extract the fixed code from the model's response."""
    # Find python code blocks
    blocks = []
    parts = response.split("```python")
    if len(parts) < 2:
        parts = response.split("```")
    for i, part in enumerate(parts[1:], 0):
        end = part.find("```")
        if end != -1:
            blocks.append(part[:end].strip())

    # If there's only one block, use it
    if len(blocks) == 1:
        return blocks[0]

    # Try to find the block that contains the file content
    # (look for function definitions from the original code)
    if len(blocks) > 1:
        # Return the largest block that looks like module code
        best = max(blocks, key=lambda b: len(b))
        return best

    return None


def score_fix(original_code: str, corrupted_code: str, fixed_code: str | None,
              corruptions: list[CorruptionSpec]) -> dict:
    """Score the model's fix by running the test suite against it."""
    if fixed_code is None:
        return {"score": 0.0, "tests_passed": 0, "tests_total": 7,
                "error": "No code block found in response"}

    # Write the fixed code to a temp dir and run tests
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        src_dir = Path(tmpdir) / "src"
        src_dir.mkdir()
        (src_dir / "math_utils.py").write_text(fixed_code)

        # Also write the test file
        test_file = Path(tmpdir) / "test_math_utils.py"
        test_content = TEST_CODE.replace("/tmp/workspace/src", str(src_dir.parent))
        test_file.write_text(test_content)

        # Run pytest
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file), "-v", "--tb=short",
                 "-o", "addopts="],
                capture_output=True, text=True, timeout=30,
                cwd=tmpdir,
            )
        except subprocess.TimeoutExpired:
            return {"score": 0.0, "tests_passed": 0, "tests_total": 7,
                    "error": "Test execution timed out"}

        stdout = result.stdout
        passed = stdout.count(" PASSED")
        failed = stdout.count(" FAILED")
        total = passed + failed
        if total == 0:
            total = 7  # fallback

        # Check how many corruptions were actually fixed
        bugs_fixed = 0
        for c in corruptions:
            if c.find in fixed_code and c.replace not in fixed_code:
                bugs_fixed += 1  # Bug was reverted (fixed)
            elif c.replace in fixed_code:
                pass  # Bug is still there

        return {
            "score": round(passed / total, 4) if total > 0 else 0.0,
            "tests_passed": passed,
            "tests_total": total,
            "bugs_fixed": bugs_fixed,
            "bugs_total": len(corruptions),
            "pytest_stdout": stdout[:500],
        }


def run_benchmark():
    """Main benchmark loop."""
    print("=" * 70)
    print(f"CODING DIFFUSION BENCHMARK — {MODEL} via {PROVIDER}")
    print("=" * 70)

    # Create PI client
    try:
        client = _make_client(None, provider=PROVIDER)
    except Exception as e:
        print(f"ERROR: Cannot create {PROVIDER} client: {e}")
        print("Run 'prime login' or set ANTHROPIC_API_KEY")
        return

    # Generate corruptions: use manual (verified visible) + pattern-generated
    pattern_corruptions = _generate_pattern_corruptions(BASE_CODE, "math_utils", max_per_file=10)
    print(f"\nPattern corruptions: {len(pattern_corruptions)}")
    for c in pattern_corruptions:
        print(f"  [{c.source_file}] {c.description[:60]} (subtlety={c.subtlety})")

    # Combine: manual first (guaranteed visible), then patterns for extra variety
    all_corruptions = list(MANUAL_CORRUPTIONS) + [c for c in pattern_corruptions
                                                    if c.corruption_id not in {m.corruption_id for m in MANUAL_CORRUPTIONS}]
    print(f"\nTotal corruptions available: {len(all_corruptions)} "
          f"({len(MANUAL_CORRUPTIONS)} manual + {len(all_corruptions) - len(MANUAL_CORRUPTIONS)} pattern)")

    # Test at each difficulty level
    results = []
    original_code = list(BASE_CODE.values())[0]

    for n_bugs in [1, 2, 3, 4, 5]:
        if len(all_corruptions) < n_bugs:
            print(f"\n{'─'*60}")
            print(f"DIFFICULTY {n_bugs}: Not enough corruptions (have {len(all_corruptions)})")
            continue

        print(f"\n{'─'*60}")
        print(f"DIFFICULTY {n_bugs}: Testing with {n_bugs} corruptions")

        # Select corruptions
        import random
        rng = random.Random(42 + n_bugs)  # Different seed per level for variety
        available = list(all_corruptions)
        rng.shuffle(available)
        selected = available[:n_bugs]

        # Apply corruptions to the original code
        corrupted = original_code
        for c in selected:
            corrupted = apply_corruptions(corrupted, [c])

        affected_files = sorted(set(c.source_file for c in selected))

        # Show what was corrupted
        print(f"  Corruptions applied:")
        for i, c in enumerate(selected, 1):
            print(f"    {i}. {c.description[:55]} (find→replace: "
                  f"{c.find[:30]!r}→{c.replace[:30]!r})")

        # Build prompt
        prompt = build_model_prompt(corrupted, n_bugs, affected_files)

        # Call the PI model
        print(f"  Calling {MODEL}...")
        start = time.time()
        try:
            if PROVIDER == "prime":
                resp = client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system="You are an expert Python debugging agent. Find and fix bugs in the code. Return the complete fixed code in ```python blocks. Do not add any explanations outside the code blocks.",
                    messages=[{"role": "user", "content": prompt}],
                )
                response_text = resp.content[0].text if hasattr(resp, 'content') else str(resp)
            else:
                resp = client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    messages=[{"role": "user", "content": prompt}],
                )
                response_text = resp.content[0].text
        except Exception as e:
            print(f"  ERROR: API call failed: {e}")
            results.append({
                "difficulty": n_bugs, "score": 0.0, "error": str(e),
                "tests_passed": 0, "tests_total": 7,
            })
            continue

        elapsed = time.time() - start
        print(f"  Response received in {elapsed:.1f}s ({len(response_text)} chars)")

        # Extract fixed code
        fixed_code = extract_fixed_code(response_text, "src/math_utils.py")

        # Score the fix
        scoring = score_fix(original_code, corrupted, fixed_code, selected)
        print(f"  Score: {scoring['score']:.2%}")
        print(f"  Tests passed: {scoring.get('tests_passed', '?')}/{scoring.get('tests_total', '?')}")
        print(f"  Bugs fixed: {scoring.get('bugs_fixed', '?')}/{scoring.get('bugs_total', '?')}")

        if scoring.get("pytest_stdout"):
            # Show first few test results
            for line in scoring["pytest_stdout"].split("\n"):
                if "PASSED" in line or "FAILED" in line:
                    print(f"    {line.strip()}")

        results.append({
            "difficulty": n_bugs,
            "n_corruptions": n_bugs,
            "elapsed_sec": round(elapsed, 1),
            **scoring,
        })

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("BENCHMARK SUMMARY")
    print(f"{'='*70}")
    print(f"  Model: {MODEL}")
    print(f"  Provider: {PROVIDER}")
    print()
    print(f"  {'Difficulty':>10} {'Score':>8} {'Tests':>10} {'Bugs Fixed':>12} {'Time':>8}")
    print(f"  {'─'*10} {'─'*8} {'─'*10} {'─'*12} {'─'*8}")
    for r in results:
        score_str = f"{r['score']:.0%}" if isinstance(r.get('score'), float) else "ERR"
        tests_str = f"{r.get('tests_passed', '?')}/{r.get('tests_total', '?')}"
        bugs_str = f"{r.get('bugs_fixed', '?')}/{r.get('bugs_total', '?')}"
        time_str = f"{r.get('elapsed_sec', '?')}s"
        print(f"  {r['difficulty']:>10} {score_str:>8} {tests_str:>10} {bugs_str:>12} {time_str:>8}")

    # Check if difficulty scales
    if len(results) > 1:
        scores = [r["score"] for r in results if "score" in r]
        if scores == sorted(scores, reverse=True):
            print(f"\n  VERDICT: YES — Score decreases as difficulty (corruption count) increases")
            print(f"           This confirms coding diffusion can simulate longer horizons")
        elif all(s >= 0.8 for s in scores):
            print(f"\n  VERDICT: Model is too strong — all scores high, no difficulty scaling visible")
            print(f"           Try more corruptions or subtler bugs")
        else:
            print(f"\n  VERDICT: MIXED — scores don't monotonically decrease")
            print(f"           Some difficulty levels may be too easy or bugs may overlap")

    # Save results
    output_path = ROOT / "results" / "diffusion_benchmark.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "model": MODEL,
        "provider": PROVIDER,
        "results": results,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, indent=2))
    print(f"\n  Results saved to: {output_path}")


if __name__ == "__main__":
    run_benchmark()
