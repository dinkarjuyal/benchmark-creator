"""Multiple-choice question generator for the pandas-understanding curriculum benchmark.

Each PANDAS_INJECTIONS entry is turned into an MCTaskCandidate:
  - prompt.txt  : source excerpt + proposed change + question stem + 4 choices
  - validator.py: reads /work/answer.json, returns {"score": 1.0|0.0, ...}
  - task.json   : harness metadata (no template workspace, no setup patches)

Curriculum levels:
  1  single function, immediate output change
  2  cross-type or cross-parameter reasoning
  3  cross-function / non-local effect
  4  transform-level or cascade effect
  5  hard negatives + false positives (correct_id may be A for hard negatives)
"""
from __future__ import annotations

import random
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.generators.pandas_injections import PANDAS_INJECTIONS


@dataclass
class MCTaskCandidate:
    """Everything needed to emit one MC task directory."""

    task_id: str
    question_type: str      # behavioral_prediction | causal_attribution | invariant_impact | counterfactual_cascade
    family: str
    difficulty: int         # 1–5
    description: str
    is_hard_negative: bool
    curriculum_note: str

    # Question content
    source_excerpt: str     # code shown to agent
    proposed_change: str    # "Replace X with Y"
    snippet: str            # code the question asks about
    question_stem: str      # "After this change, what does the snippet print?"

    # Answer choices (already shuffled with correct_id updated)
    choices: list[dict]     # [{id: "A", text: str, type: str}]
    correct_id: str         # "A" | "B" | "C" | "D"
    explanation: str        # why correct_id is correct

    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def prompt(self) -> str:
        choices_text = "\n".join(f"  {c['id']}. {c['text']}" for c in self.choices)
        source = textwrap.dedent(self.source_excerpt).strip()
        snippet = textwrap.dedent(self.snippet).strip()
        library = self.metadata.get("library_name", "pandas")
        parts = [
            f"You are given a short excerpt from the {library} source code and a proposed change.",
            "Read carefully, then answer the multiple-choice question below.",
            "",
            "─" * 50,
            "PANDAS SOURCE EXCERPT",
            "─" * 50,
            source,
            "",
            "─" * 50,
            "PROPOSED CHANGE",
            "─" * 50,
            self.proposed_change,
            "",
            "─" * 50,
            "QUESTION",
            "─" * 50,
            self.question_stem,
            "",
            "Code:",
            snippet,
            "",
            "Answer choices:",
            choices_text,
            "",
            "─" * 50,
            "INSTRUCTIONS",
            "─" * 50,
            'Write your answer to the file /work/answer.json as a JSON object.',
            'Example: {"choice": "B"}',
            "",
            "Use ONLY one of the letters A, B, C, or D.",
            "Do NOT write any explanation, code, or other text.",
            "Do NOT modify any files other than /work/answer.json.",
        ]
        return "\n".join(parts)


def _make_question_stem(inj: dict) -> str:
    qtype = inj.get("question_type", "behavioral_prediction")
    if qtype == "behavioral_prediction":
        return "After the proposed change is applied, what does the code snippet print (or do)?"
    elif qtype == "causal_attribution":
        return "After the proposed change is applied, which of the following best describes the outcome?"
    elif qtype == "counterfactual_cascade":
        return "After the proposed change is applied, which of the following is true about the snippet's output?"
    else:
        return "After the proposed change is applied, what is the result?"


def _shuffle_choices(inj: dict, seed: int | None = None) -> tuple[list[dict], str]:
    """Shuffle the four choices and return (shuffled_choices, correct_id)."""
    rng = random.Random(seed if seed is not None else hash(inj["task_id"]))

    original_choices = inj["distractors"]  # [{text, type, explanation}]
    correct_original_id = inj["correct_id"]  # "A" | "B" | "C" | "D"

    # Find the correct choice by id
    id_to_choice = {chr(65 + i): c for i, c in enumerate(original_choices)}
    correct_choice = id_to_choice[correct_original_id]

    shuffled = original_choices[:]
    rng.shuffle(shuffled)

    labeled = [
        {"id": chr(65 + i), "text": c["text"], "type": c["type"]}
        for i, c in enumerate(shuffled)
    ]

    # Find new id of the correct choice
    new_correct_id = next(
        lc["id"]
        for lc, orig in zip(labeled, shuffled)
        if orig is correct_choice
    )

    return labeled, new_correct_id


def _make_proposed_change(inj: dict) -> str:
    find = inj.get("find", "")
    replace = inj.get("replace", "")
    source_file = inj.get("source_file", "")
    if find and replace:
        return (
            f"In {source_file}:\n"
            f"  Replace: {find}\n"
            f"  With:    {replace}"
        )
    return inj.get("description", "")


class PandasMCGenerator:
    """Generates MCTaskCandidate list from PANDAS_INJECTIONS."""

    def __init__(self, shuffle_seed: int | None = 42) -> None:
        self.shuffle_seed = shuffle_seed

    def generate(self) -> list[MCTaskCandidate]:
        candidates = []
        for inj in PANDAS_INJECTIONS:
            choices, correct_id = _shuffle_choices(inj, seed=self.shuffle_seed)
            cand = MCTaskCandidate(
                task_id=inj["task_id"],
                question_type=inj.get("question_type", "behavioral_prediction"),
                family=inj["family"],
                difficulty=inj["difficulty"],
                description=inj.get("description", ""),
                is_hard_negative=inj.get("is_hard_negative", False),
                curriculum_note=inj.get("curriculum_note", ""),
                source_excerpt=inj["source_excerpt"],
                proposed_change=_make_proposed_change(inj),
                snippet=inj["snippet"],
                question_stem=_make_question_stem(inj),
                choices=choices,
                correct_id=correct_id,
                explanation=inj.get("explanation", ""),
                metadata={
                    "source_file": inj.get("source_file", ""),
                    "original_output": inj.get("original_output", ""),
                    "correct_output": inj.get("correct_output", ""),
                    "generation_recipe": f"pandas_mc injection: {inj.get('description', '')}",
                },
            )
            candidates.append(cand)
        return candidates
