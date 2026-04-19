"""Tests for the generated validator.py — the scoring engine for every MC task.

The validator is the ground truth for benchmark scores. Bugs here corrupt
all results silently. We test the template by executing the generated code
in a temporary directory with a controlled /work layout.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from scripts.generators.pandas_mc import MCTaskCandidate
from scripts.verifier_builder_mc import build_mc_validator


def _make_candidate(correct_id: str = "B", task_id: str = "test_val") -> MCTaskCandidate:
    return MCTaskCandidate(
        task_id=task_id,
        question_type="behavioral_prediction",
        family="test",
        difficulty=1,
        description="",
        is_hard_negative=False,
        curriculum_note="",
        source_excerpt="",
        proposed_change="",
        snippet="",
        question_stem="",
        choices=[{"id": l, "text": l, "type": "correct" if l == correct_id else "wrong"}
                 for l in ("A", "B", "C", "D")],
        correct_id=correct_id,
        explanation="",
    )


def _run_validator(validator_src: str, answer_json: str | None, extra_files: list[str] | None = None):
    """Run the validator in a temp dir and return parsed output dict."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        work.mkdir()

        if answer_json is not None:
            (work / "answer.json").write_text(answer_json)

        for fname in (extra_files or []):
            (work / fname).write_text("extra")

        validator_path = Path(tmp) / "validator.py"
        validator_path.write_text(validator_src)

        result = subprocess.run(
            [sys.executable, str(validator_path)],
            capture_output=True,
            text=True,
            env={**os.environ, "HARNESS_WORK_DIR": str(work)},
        )
        return json.loads(result.stdout.strip())


class TestValidatorScoring:
    def test_correct_answer_clean_workspace_scores_1(self):
        cand = _make_candidate(correct_id="B")
        src = build_mc_validator(cand)
        result = _run_validator(src, '{"choice": "B"}')
        assert result["score"] == 1.0
        assert result["passed"] is True

    def test_wrong_answer_scores_0(self):
        cand = _make_candidate(correct_id="B")
        src = build_mc_validator(cand)
        result = _run_validator(src, '{"choice": "A"}')
        assert result["score"] == 0.0
        assert result["passed"] is False

    def test_correct_answer_dirty_workspace_scores_0_8(self):
        cand = _make_candidate(correct_id="C")
        src = build_mc_validator(cand)
        result = _run_validator(src, '{"choice": "C"}', extra_files=["some_edit.py"])
        assert result["score"] == 0.8
        assert result["passed"] is False

    def test_missing_answer_file_scores_0(self):
        cand = _make_candidate(correct_id="A")
        src = build_mc_validator(cand)
        result = _run_validator(src, answer_json=None)
        assert result["score"] == 0.0
        assert "not found" in result["message"]

    def test_malformed_json_scores_0(self):
        cand = _make_candidate(correct_id="A")
        src = build_mc_validator(cand)
        result = _run_validator(src, "not json at all")
        assert result["score"] == 0.0

    def test_invalid_choice_letter_scores_0(self):
        cand = _make_candidate(correct_id="A")
        src = build_mc_validator(cand)
        result = _run_validator(src, '{"choice": "Z"}')
        assert result["score"] == 0.0

    def test_lowercase_choice_is_accepted(self):
        cand = _make_candidate(correct_id="D")
        src = build_mc_validator(cand)
        result = _run_validator(src, '{"choice": "d"}')
        assert result["score"] == 1.0

    def test_metrics_contain_choice_and_correct_id(self):
        cand = _make_candidate(correct_id="B")
        src = build_mc_validator(cand)
        result = _run_validator(src, '{"choice": "C"}')
        assert result["metrics"]["choice"] == "C"
        assert result["metrics"]["correct_id"] == "B"
        assert result["metrics"]["correct"] is False


class TestValidatorTaskIds:
    def test_correct_id_baked_into_validator(self):
        """Validator must hard-code the right answer, not read it from somewhere mutable."""
        cand = _make_candidate(correct_id="D")
        src = build_mc_validator(cand)
        assert "CORRECT_ID = 'D'" in src

    def test_task_id_baked_into_validator(self):
        cand = _make_candidate(task_id="my_task_123")
        src = build_mc_validator(cand)
        assert "my_task_123" in src
