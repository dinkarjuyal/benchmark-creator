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
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generators.adversarial_mc import FAMILIES as PANDAS_FAMILIES
from scripts.generators.adversarial_mc import (
    AdversarialMCGenerator,
    KnowledgeMCGenerator,
    RepoAnalyzer,
)
from scripts.task_writer_mc import write_mc_task


def _load_families(args: argparse.Namespace, api_key: str) -> list[dict]:
    """Resolve families: from file, from repo URL (README + issues + commits), or pandas defaults."""
    if args.families:
        return json.loads(Path(args.families).read_text())

    if args.repo:
        library_name = args.repo.rstrip("/").split("/")[-1]
        analyzer = RepoAnalyzer(api_key=api_key)
        sources: dict[str, str] = {}
        token = getattr(args, "github_token", None)

        # README (always attempted)
        try:
            print(f"[analyzer] Fetching README from {args.repo} ...")
            sources["readme"] = RepoAnalyzer.from_github(args.repo)
        except Exception as e:
            print(f"[analyzer] Warning: README fetch failed ({e})")

        # GitHub issues (graceful degradation — returns "" on failure)
        issues = RepoAnalyzer.from_github_issues(args.repo, token=token)
        if issues:
            sources["issues"] = issues
            print(f"[analyzer] Fetched issues context ({len(issues)} chars)")

        # Recent fix commits (graceful degradation)
        commits = RepoAnalyzer.from_github_commits(args.repo, token=token)
        if commits:
            sources["commits"] = commits
            print(f"[analyzer] Fetched commits context ({len(commits)} chars)")

        if not sources:
            print("[analyzer] Warning: no sources fetched. Using pandas defaults.")
            return PANDAS_FAMILIES

        try:
            families = analyzer.extract_families(sources, library_name=library_name)
        except Exception as e:
            print(f"[analyzer] Warning: extract_families failed ({e}). Using pandas defaults.")
            return PANDAS_FAMILIES

        # Optional REPL probe pass — verifies rules against installed version
        if getattr(args, "probe", False) and families:
            print("[analyzer] Running REPL probe verification (1 session + 1 LLM call per family) ...")
            families = analyzer.probe_and_filter(families, verbose=True)

        for f in families:
            f.setdefault("library_name", library_name)
        print(f"[analyzer] Extracted {len(families)} families: {[f['name'] for f in families]}")
        return families

    return PANDAS_FAMILIES


def _infer_output_dir(args: argparse.Namespace) -> Path:
    if args.output:
        p = Path(args.output)
        return p if p.is_absolute() else ROOT / p
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
    parser.add_argument("--max-tasks", type=int, default=None,
                        help="Cap total tasks per type (default: unlimited)")
    parser.add_argument("--seed", type=int, default=None,
                        help="RNG seed for reproducibility (default: Unix timestamp at run start)")
    parser.add_argument("--github-token",
                        help="GitHub personal access token for higher API rate limits (optional)")
    parser.add_argument("--probe", action="store_true",
                        help="Run REPL probe verification on extracted seed_rules (drops version-mismatched rules)")
    parser.add_argument("--dry-run", action="store_true", help="Generate but do not write task dirs")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Set ANTHROPIC_API_KEY or pass --api-key")

    # Resolve seed: explicit flag or fresh timestamp (unique per run)
    seed = args.seed if args.seed is not None else int(time.time())
    print(f"[seed] {seed}  (rerun with --seed {seed} to reproduce this question set)")

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
        gen = AdversarialMCGenerator(api_key=api_key, verbose=True, seed=seed)
        candidates = gen.generate(families=families, n_per_family=args.n)
        if args.max_tasks:
            candidates = candidates[:args.max_tasks]
        stats["adversarial"] = {"generated": len(candidates)}
        all_candidates.extend(candidates)
        print(f"[adversarial] {len(candidates)} questions verified")

    if "knowledge" in types:
        print(f"\n[knowledge] Generating behavioral-prediction questions ...")
        know_gen = KnowledgeMCGenerator(api_key=api_key, verbose=True, seed=seed)
        knowledge_cands = know_gen.generate(families=families, n_per_family=args.n)
        if args.max_tasks:
            knowledge_cands = knowledge_cands[:args.max_tasks]
        stats["knowledge"] = {"generated": len(knowledge_cands)}
        all_candidates.extend(knowledge_cands)
        print(f"[knowledge] {len(knowledge_cands)} questions")

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

    # Write benchmark.json (flat task list — backward-compatible with harness)
    benchmark_path = output_dir / "benchmark.json"
    benchmark_path.write_text(json.dumps(written, indent=2) + "\n")

    # Write generation stats (seed + repo stored here for traceability)
    stats["seed"] = seed
    stats["repo"] = args.repo or "pandas_defaults"
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
