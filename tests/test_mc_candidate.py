"""Tests for MCTaskCandidate — the data model shared by all benchmark dimensions.

Covers: prompt format, choice shuffling, task ID stability.
"""
import pytest
from scripts.generators.pandas_mc import MCTaskCandidate, _shuffle_choices


def _make_candidate(**overrides) -> MCTaskCandidate:
    defaults = dict(
        task_id="test_task_abc",
        question_type="behavioral_prediction",
        family="dtype_coercion",
        difficulty=2,
        description="Test candidate",
        is_hard_negative=False,
        curriculum_note="",
        source_excerpt="# a comment\n",
        proposed_change="Replace x with y",
        snippet="import pandas as pd\nprint(42)",
        question_stem="What does the snippet print?",
        choices=[
            {"id": "A", "text": "42",    "type": "correct"},
            {"id": "B", "text": "43",    "type": "plausible_misconception"},
            {"id": "C", "text": "None",  "type": "plausible_misconception"},
            {"id": "D", "text": "Error", "type": "exception_distractor"},
        ],
        correct_id="A",
        explanation="Prints 42.",
    )
    defaults.update(overrides)
    return MCTaskCandidate(**defaults)


class TestMCCandidatePrompt:
    def test_prompt_contains_snippet(self):
        cand = _make_candidate()
        assert "import pandas as pd" in cand.prompt
        assert "print(42)" in cand.prompt

    def test_prompt_contains_all_choices(self):
        cand = _make_candidate()
        for letter in ("A", "B", "C", "D"):
            assert f"{letter}." in cand.prompt

    def test_prompt_contains_instructions(self):
        cand = _make_candidate()
        assert "answer.json" in cand.prompt
        assert '{"choice": "B"}' in cand.prompt

    def test_prompt_contains_proposed_change(self):
        cand = _make_candidate()
        assert "Replace x with y" in cand.prompt

    def test_prompt_contains_question_stem(self):
        cand = _make_candidate()
        assert "What does the snippet print?" in cand.prompt


class TestShuffleChoices:
    """_shuffle_choices must preserve correctness while randomising position."""

    def _injection_with_correct(self, correct_id: str) -> dict:
        labels = ["A", "B", "C", "D"]
        texts  = ["opt_a", "opt_b", "opt_c", "opt_d"]
        return {
            "task_id": "shuffle_test",
            "distractors": [
                {"text": t, "type": "correct" if l == correct_id else "wrong"}
                for l, t in zip(labels, texts)
            ],
            "correct_id": correct_id,
        }

    def test_correct_choice_still_correct_after_shuffle(self):
        inj = self._injection_with_correct("B")
        choices, correct_id = _shuffle_choices(inj, seed=0)
        correct_choice = next(c for c in choices if c["id"] == correct_id)
        assert correct_choice["text"] == "opt_b"

    def test_all_four_choices_present(self):
        inj = self._injection_with_correct("A")
        choices, _ = _shuffle_choices(inj, seed=0)
        assert len(choices) == 4
        assert {c["id"] for c in choices} == {"A", "B", "C", "D"}

    def test_same_seed_is_deterministic(self):
        inj = self._injection_with_correct("C")
        _, id1 = _shuffle_choices(inj, seed=99)
        _, id2 = _shuffle_choices(inj, seed=99)
        assert id1 == id2

    def test_different_seeds_may_differ(self):
        inj = self._injection_with_correct("D")
        results = {_shuffle_choices(inj, seed=s)[1] for s in range(20)}
        # With 20 seeds and 4 possible positions, we expect >1 unique result
        assert len(results) > 1


class TestTaskId:
    def test_task_id_from_rule_is_stable(self):
        from scripts.generators.adversarial_mc import _task_id_from_rule
        id1 = _task_id_from_rule("sort=False changes order", "groupby")
        id2 = _task_id_from_rule("sort=False changes order", "groupby")
        assert id1 == id2

    def test_different_rules_give_different_ids(self):
        from scripts.generators.adversarial_mc import _task_id_from_rule
        id1 = _task_id_from_rule("rule one", "family_x")
        id2 = _task_id_from_rule("rule two", "family_x")
        assert id1 != id2

    def test_different_families_give_different_ids(self):
        from scripts.generators.adversarial_mc import _task_id_from_rule
        id1 = _task_id_from_rule("same rule", "family_a")
        id2 = _task_id_from_rule("same rule", "family_b")
        assert id1 != id2

    def test_id_contains_only_safe_chars(self):
        from scripts.generators.adversarial_mc import _task_id_from_rule
        task_id = _task_id_from_rule("sort=False + NaN → float64!", "dtype")
        assert all(c.isalnum() or c == "_" for c in task_id), f"Unsafe chars in: {task_id}"
