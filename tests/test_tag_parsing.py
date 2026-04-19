"""Tests for the XML-tag parsing helpers used by adversarial_mc.py.

These are the serialization boundary between LLM responses and our data model.
Bugs here cause silent failures (wrong questions, missing fields) rather than
loud errors, so they're high-priority to test.
"""
import pytest
from scripts.generators.adversarial_mc import _tag, _tag_all


class TestTag:
    def test_basic_extraction(self):
        text = "<rule>sort=False preserves insertion order</rule>"
        assert _tag(text, "rule") == "sort=False preserves insertion order"

    def test_strips_whitespace(self):
        text = "<rule>  leading and trailing  </rule>"
        assert _tag(text, "rule") == "leading and trailing"

    def test_multiline_content(self):
        text = "<snippet>\nimport pandas as pd\nprint(1)\n</snippet>"
        assert _tag(text, "snippet") == "import pandas as pd\nprint(1)"

    def test_missing_tag_returns_none(self):
        assert _tag("no tags here", "rule") is None

    def test_missing_close_tag_returns_none(self):
        assert _tag("<rule>only open", "rule") is None

    def test_content_with_surrounding_text(self):
        text = "Here is the rule: <rule>int + NaN → float64</rule> end."
        assert _tag(text, "rule") == "int + NaN → float64"

    def test_first_occurrence_wins(self):
        text = "<rule>first</rule> some text <rule>second</rule>"
        assert _tag(text, "rule") == "first"

    def test_empty_content(self):
        assert _tag("<rule></rule>", "rule") == ""


class TestTagAll:
    def test_multiple_occurrences(self):
        text = "<seed_rule>rule one</seed_rule><seed_rule>rule two</seed_rule>"
        assert _tag_all(text, "seed_rule") == ["rule one", "rule two"]

    def test_zero_occurrences(self):
        assert _tag_all("no tags here", "seed_rule") == []

    def test_one_occurrence(self):
        assert _tag_all("<seed_rule>only</seed_rule>", "seed_rule") == ["only"]

    def test_multiline_in_all(self):
        text = "<seed_rule>\nrule A\n</seed_rule><seed_rule>rule B</seed_rule>"
        result = _tag_all(text, "seed_rule")
        assert result == ["rule A", "rule B"]

    def test_nested_different_tags_ignored(self):
        # _tag_all only looks at the named tag, not children
        text = "<family><name>foo</name><seed_rule>r1</seed_rule></family>"
        assert _tag_all(text, "seed_rule") == ["r1"]
        assert _tag_all(text, "name") == ["foo"]
