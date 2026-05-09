"""Local-vLLM ablation runner with dual scoring (text-match + functional).

This is the H100 replacement for benchmark_ablation.py's API-driven runner.
Differences:
  - Uses vLLM offline batched inference (no API)
  - Loads the model once, batches all prompts
  - Saves prompts, raw outputs, parsed fixes, AND both scores
  - Honors the T_fail cache produced by discover_tfail.py
  - Filters corruptions to those marked HEALTHY by the cache

Usage:
    python run_eval_local.py --model Qwen/Qwen2.5-Coder-7B-Instruct \
        --domain sklearn --counts 1,3,5,7,10 --trials 3
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

os.environ.setdefault("HF_HOME", "/mnt/localssd/cdbench/hf_cache")

import scripts.benchmark_ablation as _ba
from pathlib import Path as _P
_ba.SKLEARN_ROOT = _P(os.environ.get(
    "SKLEARN_ROOT", "/mnt/localssd/cdbench/sandboxes/sklearn/sklearn"
))
_ba.SOURCE_FILES = {
    "sklearn/metrics/_classification.py": _ba.SKLEARN_ROOT / "metrics" / "_classification.py",
    "sklearn/metrics/_ranking.py": _ba.SKLEARN_ROOT / "metrics" / "_ranking.py",
    "sklearn/preprocessing/_data.py": _ba.SKLEARN_ROOT / "preprocessing" / "_data.py",
    "sklearn/linear_model/_ridge.py": _ba.SKLEARN_ROOT / "linear_model" / "_ridge.py",
    "sklearn/ensemble/_forest.py": _ba.SKLEARN_ROOT / "ensemble" / "_forest.py",
    "sklearn/model_selection/_split.py": _ba.SKLEARN_ROOT / "model_selection" / "_split.py",
}

from scripts.benchmark_ablation import (
    HAND_CORRUPTIONS,
    build_prompt,
    extract_fixed_files,
    load_snippet_files,
    apply_corruptions,
    score_fix as score_text_match,
    select_by_diversity,
)
from scripts.functional_judge import (
    SANDBOX_ROOT,
    TFAIL_CACHE,
    judge_fix,
)


def load_tfail_cache(catalog: list) -> dict[str, list[str]]:
    """Map corruption_id -> list of pytest nodeids that fail when this bug is
    applied alone."""
    out: dict[str, list[str]] = {}
    if not TFAIL_CACHE.exists():
        return out
    for c in catalog:
        for f in TFAIL_CACHE.glob(f"{c.corruption_id}_*.json"):
            data = json.loads(f.read_text())
            out[c.corruption_id] = data.get("tfail", [])
            break
    return out


def filter_healthy(catalog: list, tfail: dict[str, list[str]]) -> list:
    """Drop bugs with no T_fail tests (silent or missing)."""
    return [c for c in catalog if tfail.get(c.corruption_id)]


def make_chat_prompt(tokenizer, user_text: str, system_text: str | None = None) -> str:
    msgs = []
    if system_text:
        msgs.append({"role": "system", "content": system_text})
    msgs.append({"role": "user", "content": user_text})
    return tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)


SYSTEM_PROMPT = (
    "You are an expert Python debugging agent specializing in scikit-learn "
    "internals. Find and fix bugs. Return the complete fixed code for each "
    "affected file in separate ```python blocks with a # FILE: header."
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-7B-Instruct")
    ap.add_argument("--tp", type=int, default=2,
                    help="tensor-parallel size for vLLM")
    ap.add_argument("--max_tokens", type=int, default=8192)
    ap.add_argument("--max_model_len", type=int, default=16384)
    ap.add_argument("--gpu_util", type=float, default=0.85)
    ap.add_argument("--counts", default="1,3,5,7,10")
    ap.add_argument("--diversity", default="clustered,scattered")
    ap.add_argument("--source", default="hand")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--out_dir", default="results/local_eval")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    counts = [int(x) for x in args.counts.split(",")]
    diversity = args.diversity.split(",")

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    model_slug = args.model.replace("/", "_")
    out_path = out_dir / f"{model_slug}_n={'_'.join(map(str,counts))}_d={'_'.join(diversity)}_t{args.trials}.json"

    # ── Catalog ───────────────────────────────────────────────────────────
    tfail = load_tfail_cache(HAND_CORRUPTIONS)
    healthy = filter_healthy(HAND_CORRUPTIONS, tfail)
    print(f"Catalog: {len(HAND_CORRUPTIONS)} hand-crafted, {len(healthy)} healthy.")
    print(f"Dropped: {[c.corruption_id for c in HAND_CORRUPTIONS if c not in healthy]}")

    sandbox = SANDBOX_ROOT / "sklearn"
    if not sandbox.exists():
        raise SystemExit(f"sandbox missing: {sandbox}")

    # ── Build all prompts up front ───────────────────────────────────────
    plans = []  # list of (label, n, div, trial, corruptions, prompt, corrupted_snippets)
    import random
    rng = random.Random(args.seed)

    for n in counts:
        if n > len(healthy):
            print(f"  skipping n={n} (only {len(healthy)} healthy bugs)")
            continue
        for div in diversity:
            for trial in range(args.trials):
                pool = list(healthy)
                rng.shuffle(pool)
                selected = select_by_diversity(pool, n, div)
                if not selected:
                    continue
                snippets = load_snippet_files(selected)
                corrupted = apply_corruptions(snippets, selected)
                descs = [c.description for c in selected]
                prompt = build_prompt(corrupted, n, descs)
                label = f"n{n}_{div}_t{trial+1}"
                plans.append({
                    "label": label,
                    "n": n,
                    "diversity": div,
                    "trial": trial + 1,
                    "corruption_ids": [c.corruption_id for c in selected],
                    "corrupted_snippets": corrupted,
                    "prompt": prompt,
                    "_selected": selected,
                })
    print(f"Built {len(plans)} prompts.")

    # ── Load vLLM ─────────────────────────────────────────────────────────
    print(f"Loading {args.model} (TP={args.tp}, max_len={args.max_model_len})...")
    t0 = time.time()
    from vllm import LLM, SamplingParams
    llm = LLM(
        model=args.model,
        tensor_parallel_size=args.tp,
        gpu_memory_utilization=args.gpu_util,
        max_model_len=args.max_model_len,
        dtype="bfloat16",
        download_dir=os.environ["HF_HOME"],
    )
    print(f"  loaded in {time.time()-t0:.1f}s")
    tokenizer = llm.get_tokenizer()

    chat_prompts = [make_chat_prompt(tokenizer, p["prompt"], SYSTEM_PROMPT) for p in plans]
    sampling_params = SamplingParams(
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        top_p=1.0,
    )

    # ── Generate ──────────────────────────────────────────────────────────
    print(f"Generating {len(chat_prompts)} prompts...")
    t0 = time.time()
    outputs = llm.generate(chat_prompts, sampling_params)
    gen_dt = time.time() - t0
    n_tokens = sum(len(o.outputs[0].token_ids) for o in outputs)
    print(f"  generated {n_tokens} tokens in {gen_dt:.1f}s ({n_tokens/gen_dt:.1f} tok/s)")

    # ── Score: text-match + functional ────────────────────────────────────
    print("Scoring...")
    results = []
    for plan, out in zip(plans, outputs):
        raw = out.outputs[0].text
        fixed = extract_fixed_files(raw)

        # Text-match score (existing scorer, on snippet space)
        text_score = score_text_match(plan["corrupted_snippets"], fixed, plan["_selected"])

        # Functional score — apply fixes to the FULL sandbox source files,
        # not just snippets. We need to overlay the model's snippet fix into
        # the full source file in the sandbox.
        fixed_full_files = _expand_fixes_to_full_files(
            fixed, plan["_selected"], sandbox,
        )

        # Reset sandbox to a known-clean state via git, then apply corruptions.
        # judge_fix will overwrite with model's fix and tests run.
        # We always git-restore at the end to ensure no pollution leaks across plans.
        import subprocess as _sp
        _sp.run(["git", "checkout", "--", "sklearn/"], cwd=sandbox, check=True)
        try:
            for c in plan["_selected"]:
                target = sandbox / c.source_file
                if target.exists():
                    txt = target.read_text()
                    if c.find in txt:
                        target.write_text(txt.replace(c.find, c.replace, 1))
            func_result = judge_fix(
                plan["_selected"],
                fixed_full_files,
                sandbox,
                tfail_cache=tfail,
            )
        finally:
            _sp.run(["git", "checkout", "--", "sklearn/"], cwd=sandbox, check=True)

        results.append({
            "label": plan["label"],
            "n": plan["n"],
            "diversity": plan["diversity"],
            "trial": plan["trial"],
            "corruption_ids": plan["corruption_ids"],
            "raw_output": raw,
            "n_output_tokens": len(out.outputs[0].token_ids),
            "text_match": text_score,
            "functional": {
                "score": func_result.score,
                "fixed_count": func_result.fixed_count,
                "total_bugs": func_result.total_bugs,
                "per_bug": func_result.per_bug,
                "t_fail": func_result.t_fail,
                "t_fail_passed": func_result.t_fail_passed,
                "t_fail_still_failing": func_result.t_fail_still_failing,
                "elapsed_sec": func_result.elapsed_sec,
            },
        })
        print(f"  {plan['label']}: text_match={text_score['score']:.0%} "
              f"functional={func_result.score:.0%} "
              f"({func_result.fixed_count}/{func_result.total_bugs})")

    # ── Save ──────────────────────────────────────────────────────────────
    out_path.write_text(json.dumps({
        "model": args.model,
        "tp": args.tp,
        "temperature": args.temperature,
        "counts": counts,
        "diversity": diversity,
        "trials": args.trials,
        "n_healthy_bugs": len(healthy),
        "results": results,
        "gen_seconds": gen_dt,
        "n_output_tokens_total": n_tokens,
    }, indent=2))
    print(f"Saved {out_path}")


def _expand_fixes_to_full_files(
    fixed_snippets: dict[str, str],
    corruptions: list,
    sandbox: Path,
) -> dict[str, str]:
    """Model returned snippet-level fixes. Expand them back to full source
    files by replacing the (post-corruption) text with the (post-fix) text
    in the full sandbox source."""
    full = {}
    for rel_path, snippet_fix in fixed_snippets.items():
        sandbox_path = sandbox / rel_path
        if not sandbox_path.exists():
            continue
        # Approach: in the sandbox file, for each corruption mapped to this file,
        # if the find string is missing (because corruption is applied) and the
        # replace string is in snippet_fix's reverted form, swap it back.
        full_text = sandbox_path.read_text()
        for c in corruptions:
            if c.source_file != rel_path:
                continue
            # If snippet_fix reverted: find string is in snippet_fix and
            # replace string is not. Then we need to replace the replace
            # string in full_text with find.
            if c.find in snippet_fix and c.replace not in snippet_fix:
                if c.replace in full_text:
                    full_text = full_text.replace(c.replace, c.find, 1)
            # Otherwise leave the corruption in place (model didn't fix it)
        full[rel_path] = full_text
    return full


if __name__ == "__main__":
    main()
