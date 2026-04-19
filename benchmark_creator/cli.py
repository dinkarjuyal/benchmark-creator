"""benchmark-creator CLI — point at any Python repo, get a benchmark.

Usage:
    python3 -m benchmark_creator \\
        --repo https://github.com/pandas-dev/pandas \\
        --types adversarial \\
        --n 10 \\
        --output benchmarks/

    python3 -m benchmark_creator \\
        --repo https://github.com/psf/requests \\
        --types adversarial,knowledge \\
        --n 5

Input:
    --repo      GitHub URL or local path to a Python library repo.
                The tool fetches the README to extract behavioral families.
    --types     Comma-separated benchmark dimensions to generate:
                  adversarial  — two-player confounding questions (model is confidently wrong)
                  knowledge    — direct behavioral prediction questions (calibration baseline)
                (git_history dimension coming: mines commits for causal tracing questions)
    --n         Questions per family per seed rule (default: 3)
    --families  Path to a JSON file with pre-extracted families (skips RepoAnalyzer)
    --output    Output directory (default: benchmarks/<repo_name>)
    --api-key   Anthropic API key (or set ANTHROPIC_API_KEY env var)

Output:
    <output>/
      benchmark.json          task registry with dimension tags
      tasks/<task_id>/        one harness-compatible task dir per question
        task.json             metadata: image, timeout, validator_command
        prompt.txt            question shown to agent
        public/setup.py       no-op setup
        validator.py          scores agent's /work/answer.json
      meta/
        repo_profile.json     extracted families and seed rules
        generation_stats.json candidates generated vs. kept per filter stage
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generators.adversarial_mc import FAMILIES as PANDAS_FAMILIES
from scripts.generators.adversarial_mc import AdversarialMCGenerator, RepoAnalyzer
from scripts.task_writer_mc import write_mc_task


def _load_families(args: argparse.Namespace, api_key: str) -> list[dict]:
    """Resolve families: from file, from repo URL, or pandas defaults."""
    if args.families:
        return json.loads(Path(args.families).read_text())

    if args.repo:
        print(f"[analyzer] Fetching README from {args.repo} ...")
        try:
            readme = RepoAnalyzer.from_github(args.repo)
            library_name = args.repo.rstrip("/").split("/")[-1]
            analyzer = RepoAnalyzer(api_key=api_key)
            families = analyzer.extract_families(readme, library_name=library_name)
            print(f"[analyzer] Extracted {len(families)} families: {[f['name'] for f in families]}")
            return families
        except Exception as e:
            print(f"[analyzer] Warning: could not extract families from repo ({e}). Using pandas defaults.")

    return PANDAS_FAMILIES


def _infer_output_dir(args: argparse.Namespace) -> Path:
    if args.output:
        return Path(args.output)
    if args.repo:
        name = args.repo.rstrip("/").split("/")[-1]
        return ROOT / "benchmarks" / name
    return ROOT / "benchmarks" / "generated"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a behavioral benchmark for any Python library.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--repo", help="GitHub URL or local path to target library")
    parser.add_argument("--types", default="adversarial",
                        help="Comma-separated: adversarial,knowledge (default: adversarial)")
    parser.add_argument("--n", type=int, default=3, help="Questions per family per seed (default: 3)")
    parser.add_argument("--families", help="Path to pre-extracted families JSON (skips RepoAnalyzer)")
    parser.add_argument("--output", help="Output directory (default: benchmarks/<repo_name>)")
    parser.add_argument("--api-key", help="Anthropic API key")
    parser.add_argument("--dry-run", action="store_true", help="Generate but do not write task dirs")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Set ANTHROPIC_API_KEY or pass --api-key")

    types = [t.strip() for t in args.types.split(",")]
    output_dir = _infer_output_dir(args)
    tasks_dir = output_dir / "tasks"
    meta_dir = output_dir / "meta"

    families = _load_families(args, api_key)

    # Save repo profile for reproducibility
    if not args.dry_run:
        meta_dir.mkdir(parents=True, exist_ok=True)
        (meta_dir / "repo_profile.json").write_text(json.dumps(families, indent=2))

    all_candidates = []
    stats: dict[str, dict] = {}

    if "adversarial" in types:
        print(f"\n[adversarial] Running two-player game ({args.n} per family per seed) ...")
        gen = AdversarialMCGenerator(api_key=api_key, verbose=True)
        candidates = gen.generate(families=families, n_per_family=args.n)
        stats["adversarial"] = {"generated": len(candidates)}
        all_candidates.extend(candidates)
        print(f"[adversarial] {len(candidates)} questions verified")

    if "knowledge" in types:
        # knowledge MC uses pre-built pandas injections — repo-specific injection
        # libraries are a future extension; for now only pandas is supported
        try:
            from scripts.generators.pandas_mc import PandasMCGenerator
            print(f"\n[knowledge] Generating pandas knowledge/calibration questions ...")
            knowledge_cands = PandasMCGenerator().generate()
            stats["knowledge"] = {"generated": len(knowledge_cands)}
            all_candidates.extend(knowledge_cands)
            print(f"[knowledge] {len(knowledge_cands)} questions")
        except Exception as e:
            print(f"[knowledge] Warning: {e}")

    if args.dry_run:
        print(f"\n--- DRY RUN: {len(all_candidates)} questions, not written ---")
        for c in all_candidates:
            print(f"  {c.task_id}  type={c.question_type}  family={c.family}  correct={c.correct_id}")
        return

    tasks_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict] = []
    for cand in all_candidates:
        task_dir = write_mc_task(cand, tasks_dir)
        written.append({
            "id": cand.task_id,
            "path": str(task_dir.relative_to(ROOT)),
            "type": cand.question_type,
            "family": cand.family,
            "difficulty": cand.difficulty,
            "is_hard_negative": cand.is_hard_negative,
            "correct_id": cand.correct_id,
        })

    # Write benchmark.json
    benchmark_path = output_dir / "benchmark.json"
    benchmark_path.write_text(json.dumps(written, indent=2) + "\n")

    # Write generation stats
    stats_path = meta_dir / "generation_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2) + "\n")

    print(f"\nWrote {len(written)} tasks to {output_dir.relative_to(ROOT)}/")
    print(f"  benchmark.json  — task registry")
    print(f"  tasks/          — {len(written)} task dirs")
    print(f"  meta/           — repo_profile.json, generation_stats.json")
    print(f"\nRun benchmark:")
    print(f"  python3 -m harness.run_tasks \\")
    print(f"    --benchmark-dir {output_dir.relative_to(ROOT)} \\")
    print(f"    --agent mini_claude_haiku_4_5_mc \\")
    print(f"    --runtime local")


if __name__ == "__main__":
    main()
