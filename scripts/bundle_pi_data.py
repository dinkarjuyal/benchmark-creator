"""Bundle benchmark questions into JSONL files for the Prime Intellect environment.

Reads benchmark.json + task directories, extracts the QUESTION section from each
prompt.txt, and writes one JSONL per library to environments/benchmark_mc/data/.

Usage:
    python3 scripts/bundle_pi_data.py
    python3 scripts/bundle_pi_data.py --benchmarks pandas_understanding scikit_learn
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract_question_section(prompt_text: str) -> str:
    """Extract the QUESTION...INSTRUCTIONS block from a prompt.txt.

    Returns just the question stem + code + answer choices, stripped of the
    boilerplate header and instructions footer.
    """
    # Find QUESTION section (between QUESTION rule and INSTRUCTIONS rule)
    q_match = re.search(
        r"─+\s*\nQUESTION\s*\n─+\s*\n(.*?)(?=─+\s*\n(?:INSTRUCTIONS|$))",
        prompt_text,
        re.DOTALL,
    )
    if q_match:
        return q_match.group(1).strip()

    # Fallback: return everything after the last ──── block before Answer choices
    if "Answer choices:" in prompt_text:
        # Find the question stem — everything from after the last ─── to Answer choices
        parts = prompt_text.split("──────────────────────────────────────────────────")
        for part in reversed(parts):
            if "Answer choices:" in part:
                return part.strip()

    return prompt_text.strip()


def load_benchmark(benchmark_dir: Path) -> list[dict]:
    """Load all tasks from a benchmark directory into flat dicts."""
    benchmark_json = benchmark_dir / "benchmark.json"
    if not benchmark_json.exists():
        return []

    tasks = json.loads(benchmark_json.read_text())
    records = []

    for task in tasks:
        task_dir = ROOT / task["path"]
        prompt_file = task_dir / "prompt.txt"
        task_json_file = task_dir / "task.json"

        if not prompt_file.exists():
            print(f"  [skip] missing prompt.txt: {task['id']}")
            continue

        prompt_text = prompt_file.read_text()
        question = extract_question_section(prompt_text)

        # Load explanation from task.json _meta if available
        explanation = ""
        if task_json_file.exists():
            task_meta = json.loads(task_json_file.read_text())
            explanation = task_meta.get("_meta", {}).get("explanation", "")

        records.append({
            "id": task["id"],
            "family": task.get("family", ""),
            "difficulty": task.get("difficulty", 2),
            "is_hard_negative": task.get("is_hard_negative", False),
            "question": question,
            "correct_id": task["correct_id"],
            "explanation": explanation,
            "source_benchmark": benchmark_dir.name,
        })

    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Bundle benchmark data for PI environment")
    parser.add_argument(
        "--benchmarks", nargs="+",
        default=["pandas_understanding", "scikit_learn"],
        help="Benchmark directory names under benchmarks/ (default: pandas_understanding scikit_learn)",
    )
    parser.add_argument(
        "--output-dir", default="environments/benchmark_mc/data",
        help="Output directory for JSONL files",
    )
    args = parser.parse_args()

    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    all_records = []
    for name in args.benchmarks:
        benchmark_dir = ROOT / "benchmarks" / name
        if not benchmark_dir.exists():
            print(f"[warn] benchmark not found: {benchmark_dir}")
            continue
        records = load_benchmark(benchmark_dir)
        print(f"[{name}] {len(records)} tasks loaded")
        all_records.extend(records)

        # Per-library JSONL
        out = output_dir / f"{name}.jsonl"
        with open(out, "w") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  → {out.relative_to(ROOT)}")

    # Combined JSONL (all libraries)
    combined = output_dir / "all.jsonl"
    with open(combined, "w") as f:
        for r in all_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n[all] {len(all_records)} total tasks → {combined.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
