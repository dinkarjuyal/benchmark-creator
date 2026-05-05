"""Tests for the coding diffusion strategy.

No API key required — all LLM calls are mocked.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Data model tests ───────────────────────────────────────────────────────────

from scripts.generators.coding_diffusion import (
    CorruptionSpec,
    DiffusionSchedule,
    CodingDiffusionGenerator,
    _tag,
    _tag_all,
    _corruption_id,
    _make_client,
    _bug_variant_to_corruption,
    _generate_pattern_corruptions,
)


# ── Bug pattern integration tests ──────────────────────────────────────────────

class TestBugVariantConversion:
    """Convert BugVariant from bug_patterns to CorruptionSpec."""

    def test_variant_to_corruption(self):
        from scripts.generators.bug_patterns import BugVariant
        variant = BugVariant(
            original_code="if x < 10:\n    return True",
            buggy_code="if x <= 10:\n    return True",
            bug_description="Comparison changed: < → <=",
            bug_explanation="Off-by-one error: using <= instead of < changes boundary condition.",
            severity_level=2,
            pattern_name="off_by_one",
            line_number=1,
            changed_tokens=["<", "<="],
        )
        corruption = _bug_variant_to_corruption(variant, "src/lib.py", "boundary")
        assert corruption.source_file == "src/lib.py"
        assert corruption.family == "boundary"
        assert corruption.find == variant.original_code
        assert corruption.replace == variant.buggy_code
        assert corruption.description == variant.bug_description
        assert corruption.subtlety == 2
        assert "off_by_one" in corruption.corruption_id

    def test_variant_to_corruption_has_tests(self):
        from scripts.generators.bug_patterns import BugVariant
        variant = BugVariant(
            original_code="return True",
            buggy_code="return False",
            bug_description="Return value swapped",
            bug_explanation="Logic inverted.",
            severity_level=2,
            pattern_name="return_value",
            line_number=1,
        )
        corruption = _bug_variant_to_corruption(variant, "a.py", "test")
        assert corruption.broken_test  # non-empty
        assert corruption.passing_test  # non-empty


class TestPatternCorruptionGeneration:
    """Generate corruptions using deterministic bug patterns."""

    def test_generate_from_simple_code(self):
        # Use a function definition so _extract_test_calls can auto-generate calls
        snippets = {"src/lib.py": "def is_positive(x):\n    if x > 0:\n        return True\n    return False"}
        corruptions = _generate_pattern_corruptions(snippets, "boundary")
        assert len(corruptions) > 0
        assert all(isinstance(c, CorruptionSpec) for c in corruptions)
        assert all(c.source_file == "src/lib.py" for c in corruptions)

    def test_generate_respects_max_per_file(self):
        snippets = {"src/lib.py": "if x < 10 and y > 0:\n    return True"}
        corruptions = _generate_pattern_corruptions(snippets, "test", max_per_file=1)
        assert len(corruptions) <= 1

    def test_generate_no_corruption_from_empty_code(self):
        snippets = {"empty.py": ""}
        corruptions = _generate_pattern_corruptions(snippets, "test")
        assert len(corruptions) == 0

    def test_generate_filters_identical_output(self):
        # Code where bug doesn't change output (e.g. dead code)
        snippets = {"dead.py": "x = 1"}
        corruptions = _generate_pattern_corruptions(snippets, "test")
        # If pattern produces a variant with same output, it should be filtered
        for c in corruptions:
            # At minimum, find and replace should differ
            assert c.find != c.replace


class TestCorruptionSpec:
    """CorruptionSpec construction and field access."""

    def test_basic_construction(self):
        spec = CorruptionSpec(
            corruption_id="corr_test_abc12345",
            source_file="src/lib.py",
            find="return x + 1",
            replace="return x",
            description="Off-by-one: missing +1",
            broken_test="assert func(5) == 6  # fails after corruption",
            passing_test="assert func(5) == 5  # passes in clean code",
            family="arithmetic",
            subtlety=2,
        )
        assert spec.corruption_id == "corr_test_abc12345"
        assert spec.source_file == "src/lib.py"
        assert spec.find == "return x + 1"
        assert spec.replace == "return x"
        assert spec.subtlety == 2

    def test_subtlety_range(self):
        for s in range(1, 6):
            spec = CorruptionSpec(
                corruption_id=f"corr_subtlety_{s}",
                source_file="a.py",
                find="x",
                replace="y",
                description="test",
                broken_test="",
                passing_test="",
                family="test",
                subtlety=s,
            )
            assert spec.subtlety == s


class TestDiffusionSchedule:
    """DiffusionSchedule difficulty mapping and defaults."""

    def test_default_schedule(self):
        schedule = DiffusionSchedule()
        assert schedule.corruption_count == 3
        assert schedule.spread == "scattered"
        assert schedule.dependency == "independent"
        assert schedule.difficulty() >= 1

    def test_difficulty_increases_with_count(self):
        s1 = DiffusionSchedule(corruption_count=1)
        s3 = DiffusionSchedule(corruption_count=3)
        s5 = DiffusionSchedule(corruption_count=5)
        assert s1.difficulty() < s5.difficulty()
        assert s3.difficulty() >= s1.difficulty()

    def test_masking_increases_difficulty(self):
        s_indep = DiffusionSchedule(corruption_count=3, dependency="independent")
        s_mask = DiffusionSchedule(corruption_count=3, dependency="masking")
        assert s_mask.difficulty() >= s_indep.difficulty()

    def test_cascading_increases_difficulty(self):
        s_indep = DiffusionSchedule(corruption_count=3, dependency="independent")
        s_cascade = DiffusionSchedule(corruption_count=3, dependency="cascading")
        assert s_cascade.difficulty() >= s_indep.difficulty()

    def test_difficulty_bounded(self):
        for count in range(1, 15):
            for dep in ("independent", "cascading", "masking"):
                schedule = DiffusionSchedule(corruption_count=count, dependency=dep)
                assert 1 <= schedule.difficulty() <= 5


# ── Tag parsing tests ──────────────────────────────────────────────────────────

class TestTagParsing:
    """XML tag extraction from LLM responses."""

    def test_tag_single(self):
        text = "<description>A bug in the code</description>"
        assert _tag(text, "description") == "A bug in the code"

    def test_tag_missing(self):
        text = "no tags here"
        assert _tag(text, "description") == ""

    def test_tag_all_multiple(self):
        text = "<item>a</item><item>b</item><item>c</item>"
        assert _tag_all(text, "item") == ["a", "b", "c"]

    def test_tag_all_empty(self):
        assert _tag_all("no items", "item") == []

    def test_tag_nested_content(self):
        text = "<find>    return x + 1\n</find>"
        result = _tag(text, "find")
        assert "return x + 1" in result

    def test_corruption_block_parsing(self):
        """Test parsing a full corruption block as the LLM would produce."""
        llm_output = """\
<corruption>
<id>off_by_one</id>
<source_file>src/calculator.py</source_file>
<find>return x + 1</find>
<replace>return x</replace>
<description>Missing +1 in return value</description>
<broken_test>
assert calc(5) == 6
</broken_test>
<passing_test>
assert calc(5) == 5
</passing_test>
<subtlety>2</subtlety>
</corruption>

<corruption>
<id>swap_args</id>
<source_file>src/utils.py</source_file>
<find>merge(a, b)</find>
<replace>merge(b, a)</replace>
<description>Swapped arguments in merge call</description>
<broken_test>
assert result == "ab"
</broken_test>
<passing_test>
assert result == "ba"
</passing_test>
<subtlety>3</subtlety>
</corruption>"""

        blocks = _tag_all(llm_output, "corruption")
        assert len(blocks) == 2

        # Parse first corruption
        assert _tag(blocks[0], "id") == "off_by_one"
        assert _tag(blocks[0], "source_file") == "src/calculator.py"
        assert _tag(blocks[0], "find") == "return x + 1"
        assert _tag(blocks[0], "replace") == "return x"
        assert _tag(blocks[0], "subtlety") == "2"

        # Parse second corruption
        assert _tag(blocks[1], "id") == "swap_args"
        assert _tag(blocks[1], "source_file") == "src/utils.py"


# ── Corruption ID generation ───────────────────────────────────────────────────

class TestCorruptionId:
    """Stable ID generation from corruption metadata."""

    def test_id_deterministic(self):
        spec = {"source_file": "a.py", "find": "return 1", "description": "bug"}
        id1 = _corruption_id(spec, "test")
        id2 = _corruption_id(spec, "test")
        assert id1 == id2

    def test_id_includes_family(self):
        spec = {"source_file": "a.py", "find": "x", "description": "bug"}
        id_a = _corruption_id(spec, "family_a")
        id_b = _corruption_id(spec, "family_b")
        assert id_a != id_b

    def test_id_starts_with_corr(self):
        spec = {"source_file": "a.py", "find": "x", "description": "bug"}
        cid = _corruption_id(spec, "test")
        assert cid.startswith("corr_")


# ── Corruption selection tests ──────────────────────────────────────────────────

class TestCorruptionSelection:
    """Selection of corruptions per DiffusionSchedule constraints."""

    def _make_specs(self, n: int, same_file: bool = False) -> list[CorruptionSpec]:
        specs = []
        for i in range(n):
            specs.append(CorruptionSpec(
                corruption_id=f"corr_{i}",
                source_file="same.py" if same_file else f"file_{i}.py",
                find=f"find_{i}",
                replace=f"replace_{i}",
                description=f"corruption {i}",
                broken_test=f"assert {i}",
                passing_test="",
                family="test",
                subtlety=3,
            ))
        return specs

    def test_scattered_prefers_different_files(self):
        gen = CodingDiffusionGenerator(
            client=MagicMock(), seed=42,
            schedule=DiffusionSchedule(corruption_count=3, spread="scattered"),
        )
        specs = self._make_specs(5, same_file=False)
        selected = gen._select_corruptions(specs, DiffusionSchedule(corruption_count=3, spread="scattered"))
        assert len(selected) == 3
        # Should prefer different files
        files = {s.source_file for s in selected}
        assert len(files) >= 2  # At least 2 different files for 3 selections from 5

    def test_clustered_prefers_same_file(self):
        gen = CodingDiffusionGenerator(
            client=MagicMock(), seed=42,
            schedule=DiffusionSchedule(corruption_count=3, spread="clustered"),
        )
        # Create specs with 3 in same file and 2 in different files
        specs = []
        for i in range(3):
            specs.append(CorruptionSpec(
                corruption_id=f"corr_same_{i}",
                source_file="same.py",
                find=f"find_{i}",
                replace=f"replace_{i}",
                description=f"corruption same {i}",
                broken_test="",
                passing_test="",
                family="test",
                subtlety=3,
            ))
        for i in range(2):
            specs.append(CorruptionSpec(
                corruption_id=f"corr_diff_{i}",
                source_file=f"diff_{i}.py",
                find=f"find_d_{i}",
                replace=f"replace_d_{i}",
                description=f"corruption diff {i}",
                broken_test="",
                passing_test="",
                family="test",
                subtlety=3,
            ))
        selected = gen._select_corruptions(specs, DiffusionSchedule(corruption_count=3, spread="clustered"))
        assert len(selected) == 3
        files = {s.source_file for s in selected}
        # At least some should be from same.py
        assert "same.py" in files

    def test_select_fewer_than_requested(self):
        gen = CodingDiffusionGenerator(client=MagicMock(), seed=42)
        specs = self._make_specs(2)
        selected = gen._select_corruptions(specs, DiffusionSchedule(corruption_count=5))
        assert len(selected) == 2  # Can only select what's available

    def test_select_empty_pool(self):
        gen = CodingDiffusionGenerator(client=MagicMock(), seed=42)
        selected = gen._select_corruptions([], DiffusionSchedule(corruption_count=3))
        assert selected == []


# ── Task composition tests ─────────────────────────────────────────────────────

class TestTaskComposition:
    """Composition of corruptions into TaskCandidate."""

    def _make_specs(self) -> list[CorruptionSpec]:
        return [
            CorruptionSpec(
                corruption_id="corr_bug1_abc12345",
                source_file="src/lib.py",
                find="return x + 1",
                replace="return x",
                description="Off-by-one in return",
                broken_test="assert func(5) == 6  # fails",
                passing_test="assert func(0) == 0  # passes",
                family="arithmetic",
                subtlety=2,
            ),
            CorruptionSpec(
                corruption_id="corr_bug2_def67890",
                source_file="src/utils.py",
                find="if x > 0:",
                replace="if x >= 0:",
                description="Boundary condition off-by-one",
                broken_test="assert check(0) is False  # fails",
                passing_test="assert check(1) is True  # passes",
                family="boundary",
                subtlety=3,
            ),
        ]

    def test_compose_produces_task_candidate(self):
        gen = CodingDiffusionGenerator(client=MagicMock(), seed=42)
        family = {
            "name": "test_family",
            "description": "Test family for unit testing",
            "library_name": "testlib",
            "install": "pip install testlib",
        }
        schedule = DiffusionSchedule(corruption_count=2, spread="scattered")
        specs = self._make_specs()

        task = gen._compose_task(specs, family, schedule)
        assert task.task_id.startswith("diff_")
        assert task.task_type == "coding_diffusion"
        assert task.family == "test_family"
        assert task.difficulty >= 1
        assert len(task.visible_tests) == 2
        assert len(task.hidden_tests) == 2
        assert task.is_noop is False
        assert task.is_impossible is False

    def test_compose_metadata_contains_corruptions(self):
        gen = CodingDiffusionGenerator(client=MagicMock(), seed=42)
        family = {
            "name": "test_family",
            "description": "Test",
            "library_name": "testlib",
        }
        schedule = DiffusionSchedule(corruption_count=2)
        specs = self._make_specs()

        task = gen._compose_task(specs, family, schedule)
        meta = task.metadata
        assert "corruptions" in meta
        assert len(meta["corruptions"]) == 2
        assert meta["corruptions"][0]["source_file"] == "src/lib.py"
        assert meta["corruptions"][1]["source_file"] == "src/utils.py"

    def test_compose_metadata_contains_schedule(self):
        gen = CodingDiffusionGenerator(client=MagicMock(), seed=42)
        family = {"name": "test", "description": "test", "library_name": "testlib"}
        schedule = DiffusionSchedule(corruption_count=2, spread="clustered", dependency="masking")
        specs = self._make_specs()

        task = gen._compose_task(specs, family, schedule)
        assert task.metadata["schedule"]["spread"] == "clustered"
        assert task.metadata["schedule"]["dependency"] == "masking"
        assert task.metadata["schedule"]["corruption_count"] == 2

    def test_prompt_mentions_bug_count(self):
        gen = CodingDiffusionGenerator(client=MagicMock(), seed=42)
        family = {"name": "test", "description": "test", "library_name": "testlib"}
        schedule = DiffusionSchedule(corruption_count=2)
        specs = self._make_specs()

        task = gen._compose_task(specs, family, schedule)
        assert "2 bugs" in task.prompt


# ── Strategy registration test ─────────────────────────────────────────────────

class TestStrategyRegistration:
    """Verify coding_diffusion strategy is registered."""

    def test_strategy_registered(self):
        from scripts.generators.strategy_registry import get_strategy, list_strategies
        assert "coding_diffusion" in list_strategies()

    def test_strategy_class(self):
        from scripts.generators.strategy_registry import get_strategy
        from scripts.generators.coding_diffusion import CodingDiffusionStrategy
        cls = get_strategy("coding_diffusion")
        assert cls is CodingDiffusionStrategy

    def test_strategy_description(self):
        from scripts.generators.strategy_registry import get_strategy
        cls = get_strategy("coding_diffusion")
        desc = cls.description()
        assert "diffusion" in desc.lower() or "corruption" in desc.lower()


# ── Verifier builder test ──────────────────────────────────────────────────────

class TestDiffusionValidator:
    """Verify the diffusion validator builder produces valid Python."""

    def test_validator_is_valid_python(self):
        from scripts.verifier_builder_diffusion import build_diffusion_validator
        from scripts.generators.base import TaskCandidate

        candidate = TaskCandidate(
            task_id="diff_test_abc123",
            task_type="coding_diffusion",
            family="test",
            difficulty=3,
            prompt="Fix the bugs",
            start_state_patches={"src/lib.py": "broken code"},
            visible_tests=["assert True"],
            hidden_tests=["assert True"],
            structural_checks=[],
            generation_recipe="coding_diffusion: 2 corruptions",
            is_noop=False,
            is_impossible=False,
            metadata={
                "corruptions": [
                    {"source_file": "src/lib.py", "description": "bug1"},
                    {"source_file": "src/utils.py", "description": "bug2"},
                ],
                "schedule": {"spread": "scattered", "dependency": "independent"},
            },
        )
        validator_code = build_diffusion_validator(candidate)
        # Should be valid Python (can be compiled)
        compile(validator_code, "<validator>", "exec")
        assert "N_CORRUPTIONS" in validator_code
        assert "2" in validator_code  # 2 corruptions


# ── Task writer test ───────────────────────────────────────────────────────────

class TestDiffusionTaskWriter:
    """Verify the diffusion task writer produces valid output."""

    def test_write_diffusion_task(self, tmp_path):
        from scripts.task_writer_diffusion import write_diffusion_task
        from scripts.generators.base import TaskCandidate

        candidate = TaskCandidate(
            task_id="diff_test_writer_abc123",
            task_type="coding_diffusion",
            family="test",
            difficulty=3,
            prompt="Fix 2 bugs in the codebase.",
            start_state_patches={"src/lib.py": "broken"},
            visible_tests=["assert func() == 1"],
            hidden_tests=["assert func() == 2"],
            structural_checks=[],
            generation_recipe="coding_diffusion: 2 corruptions, scattered",
            is_noop=False,
            is_impossible=False,
            metadata={
                "corruptions": [
                    {
                        "corruption_id": "corr_1",
                        "source_file": "src/lib.py",
                        "find": "return x + 1",
                        "replace": "return x",
                        "description": "Off-by-one",
                        "family": "test",
                        "subtlety": 2,
                    },
                ],
                "schedule": {
                    "corruption_count": 1,
                    "spread": "scattered",
                    "dependency": "independent",
                },
                "library_name": "testlib",
                "install": "pip install testlib",
                "description": "1-bug debugging task",
            },
        )

        task_dir = write_diffusion_task(candidate, tmp_path)

        # Check all expected files exist
        assert (task_dir / "prompt.txt").exists()
        assert (task_dir / "validator.py").exists()
        assert (task_dir / "task.json").exists()
        assert (task_dir / "public" / "setup.py").exists()

        # Check prompt content — the task has 1 corruption so the prompt should mention it
        # Note: the prompt in the candidate is the generic one from TaskCandidate,
        # while the generated diffusion prompt is built by _build_prompt.
        # The writer just writes candidate.prompt, so check that.
        prompt = (task_dir / "prompt.txt").read_text()
        assert "bug" in prompt.lower()

        # Check task.json is valid JSON
        task_json = json.loads((task_dir / "task.json").read_text())
        assert task_json["id"] == "diff_test_writer_abc123"
        assert task_json["_meta"]["task_type"] == "coding_diffusion"

        # Check setup.py is valid Python
        setup_code = (task_dir / "public" / "setup.py").read_text()
        compile(setup_code, "<setup>", "exec")

        # Check validator is valid Python
        validator_code = (task_dir / "validator.py").read_text()
        compile(validator_code, "<validator>", "exec")


# ── Integration with CLI type dispatch ─────────────────────────────────────────

class TestCLITypeDispatch:
    """Verify the CLI can handle both MCTaskCandidate and TaskCandidate."""

    def test_mc_candidate_detection(self):
        from scripts.generators.pandas_mc import MCTaskCandidate
        cand = MCTaskCandidate(
            task_id="mc_test",
            question_type="behavioral_prediction",
            family="test",
            difficulty=1,
            description="test",
            is_hard_negative=False,
            curriculum_note="",
            source_excerpt="code",
            proposed_change="change",
            snippet="snippet",
            question_stem="stem",
            choices=[{"id": "A", "text": "ans", "type": "correct"}],
            correct_id="A",
            explanation="test",
        )
        assert isinstance(cand, MCTaskCandidate)

    def test_task_candidate_detection(self):
        from scripts.generators.base import TaskCandidate
        from scripts.generators.pandas_mc import MCTaskCandidate
        cand = TaskCandidate(
            task_id="diff_test",
            task_type="coding_diffusion",
            family="test",
            difficulty=3,
            prompt="Fix the bugs",
        )
        assert isinstance(cand, TaskCandidate)
        assert not isinstance(cand, MCTaskCandidate)
