#!/usr/bin/env python3
"""Benchmark PI models on coding diffusion tasks from the nutrain repo.

Uses real source files from nutrain (ML training library) with carefully
crafted corruptions that test multi-step debugging across:
  - router.py (expert-choice routing, gate renormalization, z-loss)
  - normalization.py (RMSNorm, AdaLN, Lipschitz constraint)
  - optimizer.py (parameter classification, Muon exclusion, grad clipping)

The corruptions are designed to:
  - Require understanding of ML training semantics
  - Have cascading effects (fixing one reveals another)
  - Be detectable by the existing test suite

Usage:
    python3 scripts/benchmark_nutrain.py
    MODEL=qwen/qwen3-coder python3 scripts/benchmark_nutrain.py
    MODEL=deepseek/deepseek-chat python3 scripts/benchmark_nutrain.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generators.coding_diffusion import _make_client, CorruptionSpec

PROVIDER = os.environ.get("PROVIDER", "prime")
MODEL = os.environ.get("MODEL", "qwen/qwen3-coder")

# ── nutrain source files ────────────────────────────────────────────────────────

ROUTER_PY = Path("/Users/dinkarjuyal/Desktop/agents/nutrain/nutrain/core/router.py")
NORM_PY = Path("/Users/dinkarjuyal/Desktop/agents/nutrain/nutrain/core/normalization.py")
OPTIM_PY = Path("/Users/dinkarjuyal/Desktop/agents/nutrain/nutrain/training/optimizer.py")

# ── Corruption definitions ──────────────────────────────────────────────────────
# Each corruption is a subtle but semantically meaningful bug in ML training code.
# Bugs are ordered by difficulty: earlier bugs are more obvious, later ones require
# deeper understanding of the training dynamics.

CORRUPTIONS = [
    # --- Difficulty 1: Obvious logic inversions ---
    CorruptionSpec(
        corruption_id="corr_nt_01_route_scale",
        source_file="nutrain/core/router.py",
        find="gating_flat = gating_flat * self.route_scale",
        replace="gating_flat = gating_flat / self.route_scale",
        description="Router: multiply by route_scale changed to divide — flips gate magnitude",
        broken_test="",
        passing_test="",
        family="router",
        subtlety=1,
    ),
    CorruptionSpec(
        corruption_id="corr_nt_02_rmsnorm_eps",
        source_file="nutrain/core/normalization.py",
        find="hidden_states = hidden_states * torch.rsqrt(variance + self.eps)",
        replace="hidden_states = hidden_states * torch.rsqrt(variance - self.eps)",
        description="RMSNorm: eps added for stability changed to subtraction — NaN near zero variance",
        broken_test="",
        passing_test="",
        family="normalization",
        subtlety=1,
    ),
    # --- Difficulty 2: Off-by-one and boundary errors ---
    CorruptionSpec(
        corruption_id="corr_nt_03_capacity_ceil",
        source_file="nutrain/core/router.py",
        find="capacity = max(1, math.ceil(self.capacity_factor * slen / self.num_experts))",
        replace="capacity = max(1, math.floor(self.capacity_factor * slen / self.num_experts))",
        description="Router: ceil→floor in capacity computation — routes fewer tokens per expert",
        broken_test="",
        passing_test="",
        family="router",
        subtlety=2,
    ),
    CorruptionSpec(
        corruption_id="corr_nt_04_adaln_scale",
        source_file="nutrain/core/normalization.py",
        find="return self.norm(x) * (1 + scale)[:, None, :] + shift[:, None, :]",
        replace="return self.norm(x) * scale[:, None, :] + shift[:, None, :]",
        description="AdaLN: removed (1 + scale) bias — scale=0 zeroes output instead of passing through",
        broken_test="",
        passing_test="",
        family="normalization",
        subtlety=2,
    ),
    # --- Difficulty 3: Semantic ML bugs ---
    CorruptionSpec(
        corruption_id="corr_nt_05_softmax_dim",
        source_file="nutrain/core/router.py",
        find="scores = F.softmax(logits.float(), dim=-1).to(logits.dtype)",
        replace="scores = F.softmax(logits.float(), dim=-2).to(logits.dtype)",
        description="Router: softmax over wrong dim (experts→tokens) — destroys expert selection",
        broken_test="",
        passing_test="",
        family="router",
        subtlety=3,
    ),
    CorruptionSpec(
        corruption_id="corr_nt_06_weight_decay_cond",
        source_file="nutrain/training/optimizer.py",
        find='return param.dim() <= 1 or "bias" in name or "norm" in name or "embedding" in name',
        replace='return param.dim() <= 1 or "bias" in name or "norm" in name',
        description="Optimizer: removed 'embedding' from no-decay check — embeddings get weight decay",
        broken_test="",
        passing_test="",
        family="optimizer",
        subtlety=3,
    ),
    # --- Difficulty 4: Subtle contract violations ---
    CorruptionSpec(
        corruption_id="corr_nt_07_expert_param_check",
        source_file="nutrain/training/optimizer.py",
        find='return ".experts." in name and any(tok in name for tok in ("gate_proj", "up_proj", "down_proj"))',
        replace='return ".experts." in name and any(tok in name for tok in ("gate_proj", "up_proj"))',
        description="Optimizer: removed 'down_proj' from expert param check — down_proj falls to AdamW",
        broken_test="",
        passing_test="",
        family="optimizer",
        subtlety=4,
    ),
    CorruptionSpec(
        corruption_id="corr_nt_08_chunk_6",
        source_file="nutrain/core/normalization.py",
        find="shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = emb.chunk(6, dim=1)",
        replace="shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = emb.chunk(5, dim=1)",
        description="AdaLN-Zero: chunk(6)→chunk(5) — wrong number of modulation signals, shape error",
        broken_test="",
        passing_test="",
        family="normalization",
        subtlety=4,
    ),
    # --- Difficulty 5: Cascading / cross-module bugs ---
    CorruptionSpec(
        corruption_id="corr_nt_09_grad_clip_add",
        source_file="nutrain/training/optimizer.py",
        find="total_norm = (dense_sq_norm + expert_sq_norm).sqrt().float()",
        replace="total_norm = (dense_sq_norm - expert_sq_norm).sqrt().float()",
        description="Grad clipping: + changed to - — subtracts expert norm, can go negative/NaN",
        broken_test="",
        passing_test="",
        family="optimizer",
        subtlety=5,
    ),
    CorruptionSpec(
        corruption_id="corr_nt_10_token_score_sums",
        source_file="nutrain/core/router.py",
        find="gating_flat = gating_flat / (token_score_sums[global_token_indices] + 1e-12)",
        replace="gating_flat = gating_flat * (token_score_sums[global_token_indices] + 1e-12)",
        description="Router: renormalization division changed to multiplication — gates explode",
        broken_test="",
        passing_test="",
        family="router",
        subtlety=5,
    ),
]


def apply_corruptions(source_files: dict[str, str], corruptions: list[CorruptionSpec]) -> dict[str, str]:
    """Apply find/replace corruptions to source files."""
    result = dict(source_files)
    for c in corruptions:
        fname = c.source_file
        if fname in result and c.find in result[fname]:
            result[fname] = result[fname].replace(c.find, c.replace, 1)
    return result


def build_prompt(corrupted_sources: dict[str, str], n_bugs: int, corruption_descs: list[str]) -> str:
    """Build the debugging prompt for the model."""
    files_section = ""
    for fname, code in corrupted_sources.items():
        files_section += f"\n### {fname}\n```python\n{code}\n```\n"

    desc_list = "\n".join(f"  {i+1}. {d}" for i, d in enumerate(corruption_descs))

    return (
        f"You are an expert ML debugging agent. The following code from the nutrain library "
        f"(a rectified-flow training framework for text-to-image models) has {n_bugs} bug(s) "
        f"introduced by a recent refactor.\n\n"
        f"Your task: find and fix ALL {n_bugs} bug(s) so that all tests pass.\n\n"
        f"Rules:\n"
        f"- Each bug is a single-point change (operator swap, function arg change, condition inversion, off-by-one)\n"
        f"- No functions were deleted or added — only existing logic was changed\n"
        f"- Fix ONLY the bugs — do not refactor or add new features\n"
        f"- Return the COMPLETE fixed code for EACH affected file in separate ```python blocks\n"
        f"- Start each code block with a comment like # FILE: nutrain/core/router.py\n\n"
        f"Bug symptom hints:\n{desc_list}\n\n"
        f"Here is the corrupted code:\n{files_section}\n"
        f"Return the COMPLETE fixed code for each affected file."
    )


def extract_fixed_files(response: str) -> dict[str, str]:
    """Extract fixed code files from model response."""
    files = {}
    # Split on ```python markers
    parts = response.split("```python")
    for part in parts[1:]:
        end = part.find("```")
        if end == -1:
            continue
        code = part[:end].strip()

        # Try multiple header formats
        fname = None
        lines = code.split("\n")

        # Check first few lines for file path
        for line in lines[:5]:
            stripped = line.strip()
            # Format: # FILE: nutrain/core/router.py
            if stripped.startswith("# FILE:"):
                fname = stripped.replace("# FILE:", "").strip()
                code = "\n".join(lines[lines.index(line)+1:]).strip()
                break
            # Format: # nutrain/core/router.py
            elif stripped.startswith("#") and "nutrain/" in stripped and stripped.endswith(".py"):
                import re
                m = re.search(r"nutrain/\S+\.py", stripped)
                if m:
                    fname = m.group(0)
                    code = "\n".join(lines[lines.index(line)+1:]).strip()
                    break
            # Format: ## nutrain/core/router.py (markdown header)
            elif stripped.startswith("##") and "nutrain/" in stripped:
                import re
                m = re.search(r"nutrain/\S+\.py", stripped)
                if m:
                    fname = m.group(0)
                    code = "\n".join(lines[lines.index(line)+1:]).strip()
                    break

        # If no header found, try to match by content signatures
        if fname is None:
            if "class ExpertChoiceRouter" in code:
                fname = "nutrain/core/router.py"
            elif "class RMSNorm" in code:
                fname = "nutrain/core/normalization.py"
            elif "def build_optimizer" in code:
                fname = "nutrain/training/optimizer.py"
            else:
                fname = f"unknown_{len(files)}.py"

        if len(code) > 50:
            files[fname] = code
    return files


def score_fix(
    original_sources: dict[str, str],
    corrupted_sources: dict[str, str],
    fixed_sources: dict[str, str],
    corruptions: list[CorruptionSpec],
) -> dict:
    """Score the model's fix by checking if each corruption was reverted.

    Two metrics:
    1. bugs_fixed: count of corruptions where the original find string is back
       (the model correctly identified and reverted the bug)
    2. no_false_fixes: count of non-corrupted code that the model didn't break
       (the model didn't introduce new bugs or break unrelated code)

    Since torch isn't available locally, we can't run the real test suite.
    Instead we verify:
    - Each corruption's `find` string is present in the fixed code
    - Each corruption's `replace` string is NOT present in the fixed code
    - The fixed code still contains key structural patterns (import lines, class defs)
    """
    bugs_fixed = 0
    bugs_detail = []

    for c in corruptions:
        fname = c.source_file
        # Check the fixed code for this file
        fixed_code = fixed_sources.get(fname, corrupted_sources.get(fname, ""))
        if not fixed_code:
            # Model didn't return this file at all
            bugs_detail.append(f"{c.corruption_id}: NOT RETURNED")
            continue

        find_present = c.find in fixed_code
        replace_absent = c.replace not in fixed_code

        if find_present and replace_absent:
            bugs_fixed += 1
            bugs_detail.append(f"{c.corruption_id}: FIXED")
        elif find_present and not replace_absent:
            bugs_detail.append(f"{c.corruption_id}: PARTIAL (find back but replace still present)")
        elif not find_present and replace_absent:
            bugs_detail.append(f"{c.corruption_id}: MISS (model changed different code)")
        else:
            bugs_detail.append(f"{c.corruption_id}: UNFIXED (replace still present)")

    # Check structural integrity — the model shouldn't break basic structure
    structural_ok = 0
    structural_checks = [
        ("nutrain/core/router.py", "class ExpertChoiceRouter"),
        ("nutrain/core/router.py", "def forward(self, router_input"),
        ("nutrain/core/normalization.py", "class RMSNorm"),
        ("nutrain/core/normalization.py", "class AdaLayerNormContinuous"),
        ("nutrain/training/optimizer.py", "def build_optimizer"),
        ("nutrain/training/optimizer.py", "def clip_grad_norm_distributed"),
    ]
    for fname, pattern in structural_checks:
        code = fixed_sources.get(fname, corrupted_sources.get(fname, ""))
        if pattern in code:
            structural_ok += 1

    return {
        "score": round(bugs_fixed / max(len(corruptions), 1), 4),
        "bugs_fixed": bugs_fixed,
        "bugs_total": len(corruptions),
        "structural_ok": structural_ok,
        "structural_total": len(structural_checks),
        "bugs_detail": bugs_detail,
    }


def main():
    print("=" * 70)
    print(f"NUTRAIN CODING DIFFUSION BENCHMARK — {MODEL}")
    print("=" * 70)

    # Load source files
    source_files = {
        "nutrain/core/router.py": ROUTER_PY.read_text(),
        "nutrain/core/normalization.py": NORM_PY.read_text(),
        "nutrain/training/optimizer.py": OPTIM_PY.read_text(),
    }
    print(f"\nLoaded {len(source_files)} source files")
    for fname, code in source_files.items():
        print(f"  {fname}: {len(code)} chars, {len(code.splitlines())} lines")

    # Verify all corruptions can be applied
    print(f"\nVerifying {len(CORRUPTIONS)} corruptions:")
    for c in CORRUPTIONS:
        found = c.find in source_files.get(c.source_file, "")
        status = "OK" if found else "MISSING"
        print(f"  [{status}] {c.corruption_id}: {c.description[:60]}")

    # Create PI client
    try:
        client = _make_client(None, provider=PROVIDER)
    except Exception as e:
        print(f"\nERROR: Cannot create {PROVIDER} client: {e}")
        return

    # Test at each difficulty level
    results = []

    for n_bugs in [1, 2, 3, 5, 7, 10]:
        if len(CORRUPTIONS) < n_bugs:
            continue

        selected = CORRUPTIONS[:n_bugs]
        corruption_descs = [c.description for c in selected]

        # Apply corruptions
        corrupted = apply_corruptions(source_files, selected)

        print(f"\n{'─'*60}")
        print(f"DIFFICULTY {n_bugs}: {len(selected)} corruptions across "
              f"{len(set(c.source_file for c in selected))} files")
        for c in selected:
            print(f"  - {c.description[:65]}")

        # Build prompt
        prompt = build_prompt(corrupted, n_bugs, corruption_descs)
        print(f"  Prompt: {len(prompt)} chars")

        # Call model
        print(f"  Calling {MODEL}...", end="", flush=True)
        start = time.time()
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=8192,
                system="You are an expert ML debugging agent. Find and fix bugs in training framework code. Return the complete fixed code for each affected file in separate ```python blocks with a # FILE: header.",
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text if hasattr(resp, "content") else str(resp)
        except Exception as e:
            print(f" ERROR: {e}")
            results.append({"difficulty": n_bugs, "score": 0.0, "error": str(e)})
            continue
        elapsed = time.time() - start
        print(f" {elapsed:.1f}s ({len(text)} chars)")

        # Extract and score
        fixed = extract_fixed_files(text)
        print(f"  Extracted {len(fixed)} files: {list(fixed.keys())}")

        scoring = score_fix(source_files, corrupted, fixed, selected)
        print(f"  Score: {scoring['score']:.0%} | Bugs fixed: {scoring['bugs_fixed']}/{scoring['bugs_total']} | Structural: {scoring['structural_ok']}/{scoring['structural_total']}")
        for d in scoring.get("bugs_detail", []):
            print(f"    {d}")

        results.append({
            "difficulty": n_bugs,
            "n_corruptions": len(selected),
            "elapsed_sec": round(elapsed, 1),
            "files_extracted": len(fixed),
            **scoring,
        })

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"  Model: {MODEL}")
    print(f"  Repo: sippycoder/nutrain (add-adversarial-benchmark branch)")
    print()
    print(f"  {'Diff':>4} {'Score':>6} {'Bugs':>8} {'Struct':>7} {'Time':>6}")
    print(f"  {'─'*4} {'─'*6} {'─'*8} {'─'*7} {'─'*6}")
    for r in results:
        s = r.get("score", 0)
        b = f"{r.get('bugs_fixed', '?')}/{r.get('bugs_total', '?')}"
        st = f"{r.get('structural_ok', '?')}/{r.get('structural_total', '?')}"
        e = f"{r.get('elapsed_sec', '?')}s"
        print(f"  {r['difficulty']:>4} {s:>6.0%} {b:>8} {st:>7} {e:>6}")

    # Save
    out = ROOT / "results" / "nutrain_diffusion_benchmark.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "model": MODEL,
        "provider": PROVIDER,
        "repo": "sippycoder/nutrain",
        "branch": "add-adversarial-benchmark",
        "corruptions": [{"id": c.corruption_id, "file": c.source_file, "desc": c.description, "subtlety": c.subtlety} for c in CORRUPTIONS],
        "results": results,
    }, indent=2))
    print(f"\n  Saved to {out}")


if __name__ == "__main__":
    main()
