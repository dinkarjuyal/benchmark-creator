"""Build a validator.py for multiple-choice (MC) tasks.

The generated validator:
  1. Reads /work/answer.json (written by the agent)
  2. Parses {"choice": "X"} from the JSON
  3. Compares to the correct answer
  4. Returns {"score": 1.0|0.0, "passed": bool, "message": str}

Policy quality:
  - 1.0 if agent wrote answer.json with valid choice AND no other pandas/ files modified
  - 0.5 if agent wrote correct answer but also modified other files
  - 0.0 if answer wrong or answer.json missing/malformed
"""
from __future__ import annotations

from scripts.generators.pandas_mc import MCTaskCandidate

_VALIDATOR_TEMPLATE = '''\
#!/usr/bin/env python3
"""Auto-generated MC validator for task: {task_id}"""
import json
import os
import sys
from pathlib import Path

CORRECT_ID = {correct_id!r}
TASK_ID = {task_id!r}
WORK = Path(os.environ.get("HARNESS_WORK_DIR", "/work"))
ANSWER_FILE = WORK / "answer.json"

def _check_extra_edits() -> bool:
    """Return True if agent only wrote answer.json (no other files modified)."""
    # Any file in /work other than answer.json counts as an extra edit
    for p in WORK.rglob("*"):
        if p.is_file() and p.name != "answer.json":
            return False
    return True


def main() -> dict:
    # --- Parse agent answer ---
    if not ANSWER_FILE.exists():
        return {{
            "score": 0.0,
            "passed": False,
            "message": "answer.json not found — agent did not write an answer",
            "metrics": {{
                "answer_found": False,
                "choice": None,
                "correct_id": CORRECT_ID,
            }},
        }}

    try:
        raw = ANSWER_FILE.read_text().strip()
        data = json.loads(raw)
        choice = str(data.get("choice", "")).upper().strip()
    except Exception as exc:
        return {{
            "score": 0.0,
            "passed": False,
            "message": f"answer.json is not valid JSON or missing 'choice' key: {{exc}}",
            "metrics": {{
                "answer_found": True,
                "choice": None,
                "correct_id": CORRECT_ID,
            }},
        }}

    if choice not in ("A", "B", "C", "D"):
        return {{
            "score": 0.0,
            "passed": False,
            "message": f"Invalid choice {{choice!r}} — must be A, B, C, or D",
            "metrics": {{
                "answer_found": True,
                "choice": choice,
                "correct_id": CORRECT_ID,
            }},
        }}

    correct = choice == CORRECT_ID
    clean = _check_extra_edits()

    if correct and clean:
        score = 1.0
    elif correct and not clean:
        score = 0.8   # correct answer but unnecessary file edits
    else:
        score = 0.0

    return {{
        "score": round(score, 4),
        "passed": score >= 1.0,
        "message": (
            f"choice={{choice}} correct={{correct}} clean_workspace={{clean}} "
            f"score={{score:.2f}}"
        ),
        "metrics": {{
            "answer_found": True,
            "choice": choice,
            "correct_id": CORRECT_ID,
            "correct": correct,
            "clean_workspace": clean,
        }},
    }}


if __name__ == "__main__":
    result = main()
    print(json.dumps(result))
'''


def build_mc_validator(candidate: MCTaskCandidate) -> str:
    """Return the source code of a validator.py for the given MC task."""
    return _VALIDATOR_TEMPLATE.format(
        task_id=candidate.task_id,
        correct_id=candidate.correct_id,
    )
