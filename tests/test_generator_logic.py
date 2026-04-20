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
    REPLSession,
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


# ─────────────────────────────────────────────────────────────────────────────
# New tests: data sources, prompts, REPLSession, probe_and_filter
# ─────────────────────────────────────────────────────────────────────────────

class TestParseOwnerName:
    def test_standard_url(self):
        owner, name = RepoAnalyzer._parse_owner_name("https://github.com/pandas-dev/pandas")
        assert owner == "pandas-dev"
        assert name == "pandas"

    def test_trailing_slash(self):
        owner, name = RepoAnalyzer._parse_owner_name("https://github.com/user/repo/")
        assert owner == "user"
        assert name == "repo"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError):
            RepoAnalyzer._parse_owner_name("https://notgithub.com/foo")


class TestFromGithubIssuesFormatting:
    """from_github_issues must format correctly and degrade gracefully."""

    def _mock_urlopen(self, data):
        import json
        from unittest.mock import patch, MagicMock
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return patch("urllib.request.urlopen", return_value=mock_resp)

    def test_formats_number_and_title(self):
        issues = [{"number": 42, "title": "NaN bug", "body": "It breaks."}]
        with self._mock_urlopen(issues):
            result = RepoAnalyzer.from_github_issues("https://github.com/pandas-dev/pandas")
        assert "#42" in result
        assert "NaN bug" in result

    def test_body_truncated_to_300_chars(self):
        long_body = "x" * 500
        issues = [{"number": 1, "title": "T", "body": long_body}]
        with self._mock_urlopen(issues):
            result = RepoAnalyzer.from_github_issues("https://github.com/pandas-dev/pandas")
        assert "x" * 301 not in result

    def test_returns_empty_string_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("network down")):
            result = RepoAnalyzer.from_github_issues("https://github.com/pandas-dev/pandas")
        assert result == ""

    def test_returns_empty_string_for_non_github_url(self):
        result = RepoAnalyzer.from_github_issues("https://gitlab.com/foo/bar")
        assert result == ""


class TestFromGithubCommitsFormatting:
    """from_github_commits must filter non-fix commits and degrade gracefully."""

    def _mock_urlopen(self, commits):
        import json
        from unittest.mock import patch, MagicMock
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(commits).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return patch("urllib.request.urlopen", return_value=mock_resp)

    def test_includes_fix_commits(self):
        commits = [
            {"sha": "abc1234ef", "commit": {"message": "fix: NaN propagation in rolling"}},
            {"sha": "def5678ab", "commit": {"message": "Fix groupby edge case"}},
        ]
        with self._mock_urlopen(commits):
            result = RepoAnalyzer.from_github_commits("https://github.com/pandas-dev/pandas")
        assert "abc1234" in result
        assert "def5678" in result

    def test_filters_non_fix_commits(self):
        commits = [
            {"sha": "abc1234ef", "commit": {"message": "fix: NaN"}},
            {"sha": "zzz9999zz", "commit": {"message": "chore: update deps"}},
            {"sha": "yyy8888yy", "commit": {"message": "docs: improve readme"}},
        ]
        with self._mock_urlopen(commits):
            result = RepoAnalyzer.from_github_commits("https://github.com/pandas-dev/pandas")
        assert "zzz9999" not in result
        assert "yyy8888" not in result
        assert "abc1234" in result

    def test_returns_empty_string_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("network down")):
            result = RepoAnalyzer.from_github_commits("https://github.com/pandas-dev/pandas")
        assert result == ""

    def test_returns_empty_string_for_non_github_url(self):
        result = RepoAnalyzer.from_github_commits("https://gitlab.com/foo/bar")
        assert result == ""


class TestRepoAnalyzerBackwardCompat:
    """extract_families must accept both a bare string (old API) and a dict."""

    _FAMILY = "<family><name>x</name><description>d</description><seed_rule>r</seed_rule><install>pip install x</install></family>"

    def _analyzer(self, llm_response: str):
        a = RepoAnalyzer.__new__(RepoAnalyzer)
        a.client = _mock_client([llm_response])
        a.model = "test"
        return a

    def test_bare_string_accepted(self):
        a = self._analyzer(self._FAMILY)
        families = a.extract_families("some readme text", library_name="pandas")
        assert len(families) == 1

    def test_dict_readme_only(self):
        a = self._analyzer(self._FAMILY)
        families = a.extract_families({"readme": "some readme"}, library_name="pandas")
        assert len(families) == 1

    def test_all_sources_passed_to_llm(self):
        a = self._analyzer(self._FAMILY)
        sources = {
            "readme": "readme text",
            "issues": "=== GITHUB ISSUES ===\n#42: NaN bug",
            "commits": "=== RECENT FIX COMMITS ===\n[abc] fix: NaN",
        }
        a.extract_families(sources, library_name="testlib")
        call_kwargs = a.client.messages.create.call_args
        user_content = call_kwargs.kwargs["messages"][0]["content"]
        assert "GITHUB ISSUES" in user_content
        assert "RECENT FIX COMMITS" in user_content

    def test_readme_only_no_issues_section_in_prompt(self):
        a = self._analyzer(self._FAMILY)
        a.extract_families({"readme": "readme text"}, library_name="testlib")
        call_kwargs = a.client.messages.create.call_args
        user_content = call_kwargs.kwargs["messages"][0]["content"]
        assert "GITHUB ISSUES" not in user_content
        assert "RECENT FIX COMMITS" not in user_content


class TestREPLSession:
    """REPLSession must run snippets in a persistent process."""

    def test_simple_print(self):
        with REPLSession() as repl:
            ok, out = repl.run("print(1 + 1)")
        assert ok
        assert out == "2"

    def test_runtime_error_returns_false(self):
        with REPLSession() as repl:
            ok, out = repl.run("print(1 / 0)")
        assert not ok
        assert "ZeroDivisionError" in out

    def test_multiple_runs_share_state(self):
        with REPLSession() as repl:
            ok1, _ = repl.run("x = 42")
            ok2, out2 = repl.run("print(x)")
        assert ok1
        assert ok2
        assert out2 == "42"

    def test_multiline_snippet(self):
        with REPLSession() as repl:
            ok, out = repl.run("result = sum(range(5))\nprint(result)")
        assert ok
        assert out == "10"


class TestProbeAndFilter:
    """probe_and_filter must drop rules that fail execution or contradict expected output."""

    def _analyzer(self, llm_response: str):
        a = RepoAnalyzer.__new__(RepoAnalyzer)
        a.client = _mock_client([llm_response])
        a.model = "test"
        return a

    def _family(self, rules):
        return {"name": "f", "description": "d", "seed_rules": rules, "install": ""}

    def test_keeps_verified_rules(self):
        probe_resp = (
            "<probe_1><snippet>print(1)</snippet><expected>1</expected></probe_1>"
            "<probe_2><snippet>print(2)</snippet><expected>2</expected></probe_2>"
        )
        a = self._analyzer(probe_resp)
        result = a.probe_and_filter([self._family(["rA", "rB"])], verbose=False)
        assert len(result) == 1
        assert result[0]["seed_rules"] == ["rA", "rB"]

    def test_drops_rule_on_wrong_output(self):
        # rule A: expected "99" but print(42) → "42"; rule B: correct
        probe_resp = (
            "<probe_1><snippet>print(42)</snippet><expected>99</expected></probe_1>"
            "<probe_2><snippet>print(42)</snippet><expected>42</expected></probe_2>"
        )
        a = self._analyzer(probe_resp)
        result = a.probe_and_filter([self._family(["rA", "rB"])], verbose=False)
        # only rB survives → 1 < 2 → family dropped
        assert result == []

    def test_family_kept_when_two_rules_survive_one_bad(self):
        probe_resp = (
            "<probe_1><snippet>print(1)</snippet><expected>1</expected></probe_1>"
            "<probe_2><snippet>print(2)</snippet><expected>2</expected></probe_2>"
            "<probe_3><snippet>print(0)</snippet><expected>99</expected></probe_3>"
        )
        a = self._analyzer(probe_resp)
        result = a.probe_and_filter([self._family(["rA", "rB", "rC"])], verbose=False)
        assert len(result) == 1
        assert result[0]["seed_rules"] == ["rA", "rB"]

    def test_family_dropped_when_fewer_than_two_survive(self):
        probe_resp = (
            "<probe_1><snippet>print(1)</snippet><expected>1</expected></probe_1>"
            "<probe_2><snippet>print(0)</snippet><expected>99</expected></probe_2>"
        )
        a = self._analyzer(probe_resp)
        result = a.probe_and_filter([self._family(["rA", "rB"])], verbose=False)
        assert result == []

    def test_family_kept_as_is_on_llm_failure(self):
        a = RepoAnalyzer.__new__(RepoAnalyzer)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("LLM down")
        a.client = mock_client
        a.model = "test"
        family = self._family(["rA", "rB"])
        result = a.probe_and_filter([family], verbose=False)
        assert result == [family]
