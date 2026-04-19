"""Tests for generator filtering logic — no API calls.

We mock the LLM client and test that the generators correctly:
- Accept valid confounders (actual ≠ rule_predicts)
- Reject non-confounders (actual == rule_predicts)
- Reject trivial confounders (actual == confirming_output)
- Build well-formed MCTaskCandidate objects
"""
import types
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from scripts.generators.adversarial_mc import (
    AdversarialMCGenerator,
    KnowledgeMCGenerator,
    RepoAnalyzer,
    _tag,
    _tag_all,
)


def _mock_client(responses: list[str]):
    """Return a mock Anthropic client that yields responses in order."""
    client = MagicMock()
    call_count = [0]

    def create(**kwargs):
        idx = call_count[0] % len(responses)
        call_count[0] += 1
        msg = MagicMock()
        msg.content = [MagicMock(text=responses[idx])]
        return msg

    client.messages.create.side_effect = create
    return client


class TestAdversarialConfounderFilter:
    """The core invariant: only keep questions where actual ≠ rule_predicts."""

    def _gen(self, responses):
        gen = AdversarialMCGenerator.__new__(AdversarialMCGenerator)
        gen.client = _mock_client(responses)
        gen.model = "test"
        gen.max_retries = 1
        gen.verbose = False
        gen.seed = None
        return gen

    def test_rejects_when_actual_equals_rule_predicts(self):
        # P1 gives a valid rule+snippet that prints "42"
        # P2 proposes a confounder where rule_predicts="42" and actual is also "42"
        p1_response = "<rule>print(42)</rule>\n<snippet>print(42)</snippet>"
        p2_response = (
            "<snippet>print(42)</snippet>\n"
            "<why_wrong>same</why_wrong>\n"
            "<rule_predicts>42</rule_predicts>"
        )
        gen = self._gen([p1_response, p2_response])
        with patch("scripts.generators.adversarial_mc._run_snippet") as mock_run:
            mock_run.return_value = (True, "42")
            family = {"name": "test", "description": "test", "seed_rules": ["r"], "install": ""}
            result = gen._run_one_round(family, "r")
        assert result is None

    def test_rejects_when_actual_is_contained_in_rule_predicts(self):
        # rule_predicts contains the actual output as a substring (verbose LLM)
        p1_response = "<rule>test rule</rule>\n<snippet>print(42)</snippet>"
        p2_response = (
            "<snippet>print(42)</snippet>\n"
            "<why_wrong>wrong</why_wrong>\n"
            "<rule_predicts>42 (because of some reason)</rule_predicts>"
        )
        gen = self._gen([p1_response, p2_response])
        with patch("scripts.generators.adversarial_mc._run_snippet") as mock_run:
            mock_run.return_value = (True, "42")
            family = {"name": "test", "description": "test", "seed_rules": ["r"], "install": ""}
            result = gen._run_one_round(family, "r")
        assert result is None

    def test_rejects_when_confounder_same_as_confirming(self):
        # Both P1 confirming and P2 confounder print the same thing
        p1_response = "<rule>test rule</rule>\n<snippet>print(1)</snippet>"
        p2_response = (
            "<snippet>print(1)</snippet>\n"
            "<why_wrong>same output</why_wrong>\n"
            "<rule_predicts>999</rule_predicts>"
        )
        gen = self._gen([p1_response, p2_response])
        with patch("scripts.generators.adversarial_mc._run_snippet") as mock_run:
            mock_run.return_value = (True, "1")
            family = {"name": "test", "description": "test", "seed_rules": ["r"], "install": ""}
            result = gen._run_one_round(family, "r")
        assert result is None

    def test_accepts_valid_confounder(self):
        # P1 prints "sorted", P2 prints "unsorted" — genuine confounder
        p1_response = "<rule>groupby sorts by default</rule>\n<snippet>print('sorted')</snippet>"
        p2_response = (
            "<snippet>print('unsorted')</snippet>\n"
            "<why_wrong>sort=False breaks this</why_wrong>\n"
            "<rule_predicts>sorted</rule_predicts>"
        )
        distractor_response = (
            "<distractor_c>Raises TypeError</distractor_c>"
            "<misconception_c>wrong type</misconception_c>"
            "<distractor_d>None</distractor_d>"
            "<misconception_d>returns nothing</misconception_d>"
        )
        gen = self._gen([p1_response, p2_response, distractor_response])

        call_n = [0]
        def fake_run(snippet, timeout=10):
            call_n[0] += 1
            return (True, "sorted") if call_n[0] == 1 else (True, "unsorted")

        with patch("scripts.generators.adversarial_mc._run_snippet", side_effect=fake_run):
            family = {"name": "groupby", "description": "groupby", "seed_rules": ["r"], "install": ""}
            result = gen._run_one_round(family, "r")

        assert result is not None
        assert result.correct_id in ("A", "B", "C", "D")
        assert result.question_type == "adversarial_confounder"

    def test_candidate_has_four_choices(self):
        p1_response = "<rule>a rule</rule>\n<snippet>print('x')</snippet>"
        p2_response = (
            "<snippet>print('y')</snippet>\n"
            "<why_wrong>different</why_wrong>\n"
            "<rule_predicts>x</rule_predicts>"
        )
        distractor_response = (
            "<distractor_c>z</distractor_c><misconception_c>m</misconception_c>"
            "<distractor_d>w</distractor_d><misconception_d>n</misconception_d>"
        )
        gen = self._gen([p1_response, p2_response, distractor_response])

        call_n = [0]
        def fake_run(snippet, timeout=10):
            call_n[0] += 1
            return (True, "x") if call_n[0] == 1 else (True, "y")

        with patch("scripts.generators.adversarial_mc._run_snippet", side_effect=fake_run):
            family = {"name": "f", "description": "d", "seed_rules": ["r"], "install": ""}
            result = gen._run_one_round(family, "r")

        assert result is not None
        assert len(result.choices) == 4
        assert {c["id"] for c in result.choices} == {"A", "B", "C", "D"}


class TestRepoAnalyzerParsing:
    """RepoAnalyzer must parse LLM tag output into the families dict format."""

    def test_extracts_families_from_tags(self):
        llm_output = """\
<family>
<name>dtype_coercion</name>
<description>int/float promotion rules</description>
<seed_rule>int + NaN becomes float64</seed_rule>
<seed_rule>apply() can change dtype</seed_rule>
<install>pip install pandas</install>
</family>
<family>
<name>groupby_sort</name>
<description>sort order semantics</description>
<seed_rule>sort=False preserves insertion order</seed_rule>
<install>pip install pandas</install>
</family>"""
        analyzer = RepoAnalyzer.__new__(RepoAnalyzer)
        analyzer.client = _mock_client([llm_output])
        analyzer.model = "test"

        families = analyzer.extract_families("some readme", library_name="pandas")
        assert len(families) == 2
        assert families[0]["name"] == "dtype_coercion"
        assert families[1]["name"] == "groupby_sort"
        assert len(families[0]["seed_rules"]) == 2
        assert families[0]["seed_rules"][0] == "int + NaN becomes float64"
        assert families[0]["install"] == "pip install pandas"

    def test_skips_family_with_missing_name(self):
        llm_output = """\
<family>
<description>no name here</description>
<seed_rule>some rule</seed_rule>
</family>"""
        analyzer = RepoAnalyzer.__new__(RepoAnalyzer)
        analyzer.client = _mock_client([llm_output])
        analyzer.model = "test"

        families = analyzer.extract_families("readme", library_name="lib")
        assert families == []

    def test_skips_family_with_no_seed_rules(self):
        llm_output = "<family><name>empty</name><description>d</description></family>"
        analyzer = RepoAnalyzer.__new__(RepoAnalyzer)
        analyzer.client = _mock_client([llm_output])
        analyzer.model = "test"

        families = analyzer.extract_families("readme", library_name="lib")
        assert families == []
