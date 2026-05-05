#!/usr/bin/env python3
"""Test coding diffusion on Prime Intellect with increasing horizon.

Demonstrates that:
  1. Pattern-based corruption generation works at increasing step counts
  2. Multi-bug composition scales difficulty
  3. PI models (Qwen) can generate corruptions via the LLM path
  4. Longer horizons (more sequential corruptions) produce harder tasks

Usage:
    python3 scripts/test_coding_diffusion_horizon.py
    # Override model:
    PROVIDER=prime MODEL=qwen/qwen3-8b python3 scripts/test_coding_diffusion_horizon.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generators.coding_diffusion import (
    CorruptionSpec,
    DiffusionSchedule,
    CodingDiffusionGenerator,
    _bug_variant_to_corruption,
    _generate_pattern_corruptions,
    _make_client,
)
from scripts.generators.bug_patterns import inject_bugs, get_all_patterns, BugVariant
from scripts.generators.runtime import PythonRuntime

# ── Config ─────────────────────────────────────────────────────────────────────

PROVIDER = os.environ.get("PROVIDER", "prime")
MODEL = os.environ.get("MODEL", "qwen/qwen3-8b" if PROVIDER == "prime" else "claude-sonnet-4-6")
VERBOSE = True

# Sample code snippets for pattern-based testing
SAMPLE_CODE = {
    "src/calculator.py": """\
def calculate_average(numbers):
    total = sum(numbers)
    count = len(numbers)
    if count <= 0:
        return None
    return total / count

def is_positive(x):
    if x > 0:
        return True
    return False
""",
    "src/validator.py": """\
def validate_input(value):
    if value is None:
        raise ValueError("Value cannot be None")
    if type(value) is not int:
        return False
    if value < 0 or value > 100:
        return False
    return True

def check_range(items):
    for i in range(len(items)):
        if items[i] < 0:
            return False
    return True
""",
    "src/transform.py": """\
def safe_divide(a, b):
    if b == 0:
        return None
    result = int(a) / int(b)
    return result

def get_first(items):
    return items[0]

def clamp(value, min_val, max_val):
    if value < min_val:
        return min_val
    if value > max_val:
        return max_val
    return value
""",
}

# ── Phase 1: Pattern-based fast path ───────────────────────────────────────────

def test_pattern_corruption_horizon():
    """Test that increasing corruptions produces harder tasks."""
    print("\n" + "=" * 70)
    print("PHASE 1: Pattern-based Corruption Generation (No API Cost)")
    print("=" * 70)

    # First, show what patterns are available
    print("\n  Available bug patterns:")
    for pattern_cls in get_all_patterns():
        p = pattern_cls()
        print(f"    - {p.pattern_name} (severity={p.severity_level})")

    # Test at each horizon level
    results = []
    for n_bugs in [1, 3, 5, 7]:
        schedule = DiffusionSchedule(
            corruption_count=n_bugs,
            spread="scattered",
            dependency="independent",
        )

        # Generate corruptions using patterns
        all_corruptions: list[CorruptionSpec] = []
        for source_file, code in SAMPLE_CODE.items():
            corruptions = _generate_pattern_corruptions(
                {source_file: code}, "test_family", max_per_file=n_bugs
            )
            all_corruptions.extend(corruptions)

        if not all_corruptions:
            print(f"\n  Horizon {n_bugs}: No corruptions generated (need more varied code)")
            continue

        # Select N corruptions
        import random
        rng = random.Random(42)
        rng.shuffle(all_corruptions)
        selected = all_corruptions[:n_bugs]

        difficulty = schedule.difficulty()
        families = set(c.family for c in selected)
        files = set(c.source_file for c in selected)
        patterns = set(c.description[:50] for c in selected)
        subtleties = [c.subtlety for c in selected]

        print(f"\n  Horizon {n_bugs} (difficulty={difficulty}):")
        print(f"    Corruptions: {len(selected)}")
        print(f"    Files affected: {len(files)} → {sorted(files)}")
        print(f"    Subtlety range: {min(subtleties)}-{max(subtleties)}")
        print(f"    Patterns used:")
        for c in selected:
            print(f"      [{c.source_file}] {c.description[:60]}")

        # Compose into a task
        family = {
            "name": "test_family",
            "description": "Test family for horizon scaling",
            "library_name": "testlib",
            "install": "pip install testlib",
        }
        gen = CodingDiffusionGenerator(
            client=None, verbose=False, seed=42,
        )
        task = gen._compose_task(selected, family, schedule)

        print(f"    Task ID: {task.task_id}")
        print(f"    Task type: {task.task_type}")
        print(f"    Difficulty: {task.difficulty}")
        print(f"    Visible tests: {len(task.visible_tests)}")
        print(f"    Hidden tests: {len(task.hidden_tests)}")
        print(f"    Prompt preview: {task.prompt[:120]}...")

        results.append({
            "horizon": n_bugs,
            "difficulty": difficulty,
            "corruptions": len(selected),
            "files": len(files),
            "task_id": task.task_id,
        })

    # Summary
    print("\n  ── Horizon Scaling Summary ──")
    print(f"  {'Horizon':>8} {'Difficulty':>10} {'Corruptions':>12} {'Files':>6}")
    print(f"  {'─'*8} {'─'*10} {'─'*12} {'─'*6}")
    for r in results:
        print(f"  {r['horizon']:>8} {r['difficulty']:>10} {r['corruptions']:>12} {r['files']:>6}")

    return results


# ── Phase 2: Verify execution difference ────────────────────────────────────────

def test_bug_visibility():
    """Verify that each pattern corruption actually changes output."""
    print("\n" + "=" * 70)
    print("PHASE 2: Bug Visibility Verification")
    print("=" * 70)

    runtime = PythonRuntime()

    for source_file, code in SAMPLE_CODE.items():
        print(f"\n  File: {source_file}")
        # Run original
        ok_orig, out_orig = runtime.run(code, timeout=5)
        if not ok_orig:
            print(f"    Original: ERROR - {out_orig[:80]}")
            continue
        print(f"    Original output: {out_orig[:100]}")

        # Apply each pattern
        variants = inject_bugs(code, max_variants=10)
        visible_count = 0
        for v in variants:
            ok_buggy, out_buggy = runtime.run(v.buggy_code, timeout=5)
            if ok_buggy and out_buggy != out_orig:
                visible_count += 1
                print(f"    [{v.pattern_name}] VISIBLE: output changed")
            elif ok_buggy:
                print(f"    [{v.pattern_name}] INVISIBLE: output same")
            else:
                err_preview = out_buggy[:60]
                print(f"    [{v.pattern_name}] CRASH: {err_preview}")

        print(f"    Visible bugs: {visible_count}/{len(variants)}")


# ── Phase 3: LLM-based generation via Prime Intellect ──────────────────────────

def test_llm_generation_pi():
    """Test LLM-based corruption generation using Prime Intellect API."""
    print("\n" + "=" * 70)
    print(f"PHASE 3: LLM-based Generation via {PROVIDER} ({MODEL})")
    print("=" * 70)

    try:
        client = _make_client(None, provider=PROVIDER)
    except Exception as e:
        print(f"  SKIP: Cannot create {PROVIDER} client: {e}")
        print(f"  Run 'prime login' or set ANTHROPIC_API_KEY")
        return None

    # Define a family with seed rules
    family = {
        "name": "boundary_conditions",
        "description": "Off-by-one, boundary, and edge case bugs in comparison and loop logic",
        "seed_rules": [
            "Comparison operators (< vs <=) change boundary conditions",
            "Loop range bounds determine iteration count",
            "Null/None checks guard against missing values",
            "Return values determine function output",
        ],
        "install": "pip install testlib",
        "library_name": "testlib",
    }

    gen = CodingDiffusionGenerator(
        client=client,
        model=MODEL,
        verbose=VERBOSE,
        seed=42,
    )

    # Test at each horizon level
    results = []
    for n_bugs in [2, 4, 6]:
        schedule = DiffusionSchedule(
            corruption_count=n_bugs,
            spread="scattered",
            dependency="independent",
        )
        gen.schedule = schedule

        print(f"\n  Generating {n_bugs}-corruption task via {MODEL}...")
        start = time.time()

        try:
            candidates = gen.generate(
                families=[family],
                n_per_family=1,
                schedule=schedule,
            )
        except Exception as e:
            print(f"    ERROR: {e}")
            continue

        elapsed = time.time() - start

        if not candidates:
            print(f"    No candidates generated (need more source context or API calls)")
            continue

        task = candidates[0]
        print(f"    Generated in {elapsed:.1f}s")
        print(f"    Task ID: {task.task_id}")
        print(f"    Difficulty: {task.difficulty}")
        print(f"    Corruptions in metadata: {len(task.metadata.get('corruptions', []))}")
        print(f"    Visible tests: {len(task.visible_tests)}")
        print(f"    Prompt preview: {task.prompt[:200]}...")

        # Show corruption details
        for i, c in enumerate(task.metadata.get("corruptions", []), 1):
            print(f"    Bug {i}: {c.get('description', '?')[:60]} "
                  f"({c.get('source_file', '?')}, subtlety={c.get('subtlety', '?')})")

        results.append({
            "horizon": n_bugs,
            "difficulty": task.difficulty,
            "task_id": task.task_id,
            "elapsed": elapsed,
        })

    return results


# ── Phase 4: Compose multi-step diffusion ────────────────────────────────────

def test_sequential_diffusion():
    """Test that sequential corruptions create progressively harder tasks.

    The key insight: in diffusion models, each step adds noise.
    Here, each corruption step adds a bug. More steps = harder to reverse.
    """
    print("\n" + "=" * 70)
    print("PHASE 4: Sequential Diffusion - Difficulty Scaling")
    print("=" * 70)

    # Use a richer codebase for multi-step
    complex_code = {
        "src/engine.py": """\
import math

def compute_score(values, weights=None):
    if weights is None:
        weights = [1.0] * len(values)
    if len(values) != len(weights):
        raise ValueError("Length mismatch")
    total = 0.0
    for i in range(len(values)):
        total += values[i] * weights[i]
    return total

def normalize(data):
    if not data:
        return []
    max_val = max(data)
    if max_val == 0:
        return data
    return [x / max_val for x in data]

def threshold_filter(values, cutoff):
    result = []
    for v in values:
        if v > cutoff:
            result.append(v)
    return result

def safe_sqrt(x):
    if x < 0:
        return None
    return math.sqrt(x)

def percentile(data, p):
    if not data:
        return None
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    if idx >= len(sorted_data):
        idx = len(sorted_data) - 1
    return sorted_data[idx]
""",
    }

    runtime = PythonRuntime()
    results = []

    for n_bugs in [1, 2, 3, 4, 5]:
        schedule = DiffusionSchedule(
            corruption_count=n_bugs,
            spread="scattered" if n_bugs > 1 else "clustered",
            dependency="independent" if n_bugs <= 3 else "cascading",
        )

        # Generate all available pattern corruptions
        all_corruptions = _generate_pattern_corruptions(
            complex_code, "engine", max_per_file=5
        )

        if len(all_corruptions) < n_bugs:
            print(f"\n  Horizon {n_bugs}: Not enough pattern corruptions "
                  f"(have {len(all_corruptions)}, need {n_bugs})")
            continue

        # Select and compose
        import random
        rng = random.Random(42)
        rng.shuffle(all_corruptions)
        selected = all_corruptions[:n_bugs]

        family = {
            "name": "engine",
            "description": "Scoring and math engine",
            "library_name": "engine",
        }
        gen = CodingDiffusionGenerator(client=None, verbose=False, seed=42)
        task = gen._compose_task(selected, family, schedule)

        # Count how many corruptions are actually visible (change output)
        visible = 0
        for c in selected:
            ok_o, out_o = runtime.run(c.find, timeout=5)
            ok_b, out_b = runtime.run(c.replace, timeout=5)
            if ok_o and ok_b and out_o != out_b:
                visible += 1

        difficulty = schedule.difficulty()
        print(f"\n  Horizon {n_bugs} (spread={schedule.spread}, "
              f"dep={schedule.dependency}):")
        print(f"    Difficulty score: {difficulty}/5")
        print(f"    Corruptions: {len(selected)}")
        print(f"    Visible corruptions: {visible}/{len(selected)}")
        print(f"    Files affected: {len(set(c.source_file for c in selected))}")
        print(f"    Subtlety range: {min(c.subtlety for c in selected)}-"
              f"{max(c.subtlety for c in selected)}")
        for i, c in enumerate(selected, 1):
            print(f"    Step {i}: {c.description[:50]} (subtlety={c.subtlety})")

        results.append({
            "horizon": n_bugs,
            "difficulty": difficulty,
            "corruptions": len(selected),
            "visible": visible,
            "spread": schedule.spread,
            "dependency": schedule.dependency,
        })

    # Print scaling summary
    print("\n  ── Diffusion Step Scaling ──")
    print(f"  {'Steps':>6} {'Diff':>5} {'Bugs':>5} {'Visible':>8} {'Spread':>10} {'Dep':>10}")
    print(f"  {'─'*6} {'─'*5} {'─'*5} {'─'*8} {'─'*10} {'─'*10}")
    for r in results:
        print(f"  {r['horizon']:>6} {r['difficulty']:>5} {r['corruptions']:>5} "
              f"{r['visible']:>8} {r['spread']:>10} {r['dependency']:>10}")

    return results


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("CODING DIFFUSION HORIZON TEST")
    print(f"Provider: {PROVIDER} | Model: {MODEL}")
    print("=" * 70)

    # Phase 1: Pattern-based (free, no API)
    p1_results = test_pattern_corruption_horizon()

    # Phase 2: Visibility verification
    test_bug_visibility()

    # Phase 3: LLM via PI (requires API key)
    p3_results = test_llm_generation_pi()

    # Phase 4: Sequential diffusion scaling
    p4_results = test_sequential_diffusion()

    # Final verdict
    print("\n" + "=" * 70)
    print("VERDICT: Does increasing diffusion steps increase difficulty?")
    print("=" * 70)

    if p4_results:
        difficulties = [r["difficulty"] for r in p4_results]
        horizons = [r["horizon"] for r in p4_results]
        if difficulties == sorted(difficulties) and len(difficulties) > 1:
            print(f"  YES: Difficulty monotonically increases with horizon")
            print(f"       Horizons: {horizons}")
            print(f"       Difficulties: {difficulties}")
        else:
            print(f"  PARTIAL: Difficulty does not always increase")
            print(f"       Horizons: {horizons}")
            print(f"       Difficulties: {difficulties}")

        # Check visibility ratio
        vis_ratios = [r["visible"] / max(r["corruptions"], 1) for r in p4_results]
        if all(r >= 0.5 for r in vis_ratios):
            print(f"  YES: Most corruptions are visible (change output)")
            print(f"       Visibility ratios: {[f'{r:.0%}' for r in vis_ratios]}")
        else:
            print(f"  WARNING: Many corruptions are invisible")
            print(f"       Visibility ratios: {[f'{r:.0%}' for r in vis_ratios]}")
    else:
        print("  INCONCLUSIVE: Not enough data points")

    # Save results
    output_path = ROOT / "benchmarks" / "diffusion_horizon_test.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "phase1_pattern": p1_results,
        "phase3_llm": p3_results or [],
        "phase4_sequential": p4_results,
        "config": {"provider": PROVIDER, "model": MODEL},
    }, indent=2))
    print(f"\n  Results saved to: {output_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
