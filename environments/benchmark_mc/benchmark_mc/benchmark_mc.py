"""Behavioral benchmark MCQ environment for Prime Intellect RL training.

Tests a model's ability to predict non-obvious library behavior — specifically
the boundary cases where a known rule breaks. Every question is execution-verified:
the confirming snippet and confounder were both run before inclusion.

The adversarial design means the hard negative is always the output a model
confidently applying a known rule would predict, making wrong answers a signal
of overgeneralization rather than mere ignorance.

Usage:
    prime eval run benchmark_mc -m openai/gpt-4.1-mini -n 20

    # Target a specific library
    prime eval run benchmark_mc -m openai/gpt-4.1-mini --env-args '{"library": "pandas"}'

    # Evaluate both with a smaller model
    prime eval run benchmark_mc -m openai/Qwen/Qwen2.5-1.5B-Instruct -n 20

For RL training (hosted):
    # environment provides reward_fn compatible with prime-rl rollouts
    prime lab setup --prime-rl
"""
from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path

import verifiers as vf
from datasets import Dataset

# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """\
You are an expert Python developer. When shown a code snippet, reason step by step \
through its execution before answering. Pay close attention to:
- Library-specific edge cases that differ from general Python behavior
- Cases where a rule that usually holds actually breaks
- Subtle differences between similar-looking API calls
- PyTorch dtype promotion rules and mixed-precision edge cases
- Distributed training semantics (FSDP, expert parallelism, tensor sharding)

Think through the code carefully, then give your final answer as a single letter \
on the last line: A, B, C, or D."""

_COT_SUFFIX = "\n\nThink step by step. Give your final answer as a single letter (A, B, C, or D) on the last line."

# ── Data loading ───────────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).parent / "data"

_LIBRARY_FILES = {
    "pandas": "pandas_understanding.jsonl",
    "scikit_learn": "scikit_learn.jsonl",
    "nutrain": "nutrain.jsonl",
    "all": "all.jsonl",
}


def _load_records(library: str) -> list[dict]:
    """Load bundled JSONL records for a library (or all)."""
    filename = _LIBRARY_FILES.get(library)
    if filename is None:
        raise ValueError(
            f"Unknown library {library!r}. "
            f"Choose from: {list(_LIBRARY_FILES.keys())}"
        )
    path = _DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Data file not found: {path}. "
            "Run scripts/bundle_pi_data.py to regenerate."
        )
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ── Reward function ────────────────────────────────────────────────────────────

async def _score_answer(completion, answer) -> float:
    """Score: 1.0 if model picks correct letter, 0.0 otherwise.

    Extracts the last standalone A/B/C/D from the model's response.
    This rewards chain-of-thought: the model can reason freely, then
    commit to a letter at the end.
    """
    response = completion[-1]["content"].strip()

    # 1. Check the very last non-empty line for a bare letter
    lines = [l.strip() for l in response.split("\n") if l.strip()]
    if lines:
        last = lines[-1].upper()
        # e.g. "B", "Answer: B", "The answer is B."
        m = re.search(r"\b([A-D])\b", last)
        if m:
            return 1.0 if m.group(1) == answer.upper() else 0.0

    # 2. Fallback: last occurrence of a standalone letter in the whole response
    all_letters = re.findall(r"\b([A-D])\b", response.upper())
    if all_letters:
        return 1.0 if all_letters[-1] == answer.upper() else 0.0

    return 0.0


async def _format_reward(completion, answer) -> float:
    """Partial reward (0.2) for responding with any valid letter at all.

    Encourages the model to commit to an answer rather than abstaining,
    which helps RL exploration early in training.
    """
    response = completion[-1]["content"].strip()
    if re.search(r"\b[A-D]\b", response.upper()):
        return 0.2
    return 0.0


# ── Environment factory ────────────────────────────────────────────────────────

def load_environment(
    library: str = "all",
    max_examples: int | None = None,
    chain_of_thought: bool = True,
    format_reward_weight: float = 0.0,
) -> vf.Environment:
    """Load behavioral benchmark MCQ environment.

    Args:
        library: Which benchmark to load. One of "pandas", "scikit_learn", "nutrain", "all".
        max_examples: Cap number of examples (None = use all).
        chain_of_thought: If True, append a CoT instruction to each prompt.
            Recommended for RL training — rewards structured reasoning.
        format_reward_weight: Weight [0, 1] for format reward (answered with any
            letter). Set > 0 early in training to encourage exploration, then
            anneal to 0. Default 0 = correctness only.

    Returns:
        vf.SingleTurnEnv ready for prime eval run or RL training.

    Examples:
        # Pure correctness signal (best for evaluation)
        env = load_environment(library="pandas")

        # With format reward for RL bootstrap (anneal after ~50 steps)
        env = load_environment(library="all", chain_of_thought=True,
                               format_reward_weight=0.2)
    """
    records = _load_records(library)

    if max_examples is not None:
        records = records[:max_examples]

    def _build_prompt(rec: dict) -> list[dict]:
        question = rec["question"]
        if chain_of_thought:
            question = question + _COT_SUFFIX
        return [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": question},
        ]

    dataset = Dataset.from_list([
        {
            "prompt": _build_prompt(rec),
            "answer": rec["correct_id"],
            # Pass through metadata as info — accessible in rubric funcs
            "info": json.dumps({
                "family": rec["family"],
                "difficulty": rec["difficulty"],
                "is_hard_negative": rec["is_hard_negative"],
                "explanation": rec["explanation"],
                "source_benchmark": rec["source_benchmark"],
            }),
        }
        for rec in records
    ])

    # Build rubric — optionally combine correctness + format signals
    if format_reward_weight > 0:
        import verifiers as vf_inner

        async def weighted_reward(completion, answer, info) -> float:
            correctness = await _score_answer(completion, answer)
            # If correct, full credit; if wrong but answered, small partial
            if correctness == 1.0:
                return 1.0
            fmt = await _format_reward(completion, answer)
            return fmt * format_reward_weight

        rubric = vf.Rubric(funcs=[weighted_reward])
    else:
        rubric = vf.Rubric(funcs=[_score_answer])

    env = vf.SingleTurnEnv(dataset=dataset, rubric=rubric)

    return env
