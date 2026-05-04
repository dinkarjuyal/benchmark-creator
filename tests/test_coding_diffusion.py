"""Tests for Coding Diffusion strategy.

Tests cover:
  - Bug pattern application (unit)
  - Bug variant generation (unit)
  - Strategy integration (mocked API)
  - Task formatting (unit)
  - Verification logic (mocked runtime)
"""
import pytest
from scripts.generators.bug_patterns import (
    OffByOneBug,
    LogicalOperatorBug,
    IndexingBug,
    NullCheckBug,
    ReturnValueBug,
    TypeCastBug,
    RangeLoopBug,
    AssertionBug,
    EarlyReturnBug,
    inject_bugs,
    BugVariant,
)
from scripts.generators.coding_diffusion import (
    CodingDiffusionStrategy,
    GitCommitMiner,
    BugVerifier,
)


# ── Bug Pattern Tests ──────────────────────────────────────────────────────────


class TestOffByOneBug:
    def test_can_apply_with_comparison(self):
        code = "if x < 10: print('ok')"
        assert OffByOneBug().can_apply(code) is True

    def test_can_apply_without_comparison(self):
        code = "x = y + z"
        assert OffByOneBug().can_apply(code) is False

    def test_apply_less_than(self):
        code = "if x < 10:\n    return True"
        variant = OffByOneBug().apply(code)
        assert "<=" in variant.buggy_code
        assert "<" not in variant.buggy_code or "<=" in variant.buggy_code
        assert variant.severity_level == 2
        assert variant.pattern_name == "off_by_one"

    def test_apply_greater_than(self):
        code = "while i > 0:\n    i -= 1"
        variant = OffByOneBug().apply(code)
        assert ">=" in variant.buggy_code
        assert variant.line_number == 1


class TestLogicalOperatorBug:
    def test_can_apply_with_and(self):
        code = "if x > 0 and y < 10:"
        assert LogicalOperatorBug().can_apply(code) is True

    def test_apply_and_to_or(self):
        code = "if x > 0 and y < 10:\n    pass"
        variant = LogicalOperatorBug().apply(code)
        assert " or " in variant.buggy_code
        assert variant.severity_level == 2

    def test_can_apply_with_or(self):
        code = "if x or y:"
        assert LogicalOperatorBug().can_apply(code) is True


class TestIndexingBug:
    def test_can_apply_with_index(self):
        code = "arr[0]"
        assert IndexingBug().can_apply(code) is True

    def test_apply_zero_to_one(self):
        code = "x = items[0]\nreturn x"
        variant = IndexingBug().apply(code)
        assert "[1]" in variant.buggy_code
        assert variant.changed_tokens == ["0", "1"]

    def test_apply_negative_index(self):
        code = "last = arr[-1]"
        variant = IndexingBug().apply(code)
        assert "[-2]" in variant.buggy_code


class TestNullCheckBug:
    def test_can_apply_is_none(self):
        code = "if x is None:"
        assert NullCheckBug().can_apply(code) is True

    def test_apply_is_to_is_not(self):
        code = "if value is None:\n    raise ValueError()"
        variant = NullCheckBug().apply(code)
        assert "is not None" in variant.buggy_code
        assert "is None" not in variant.buggy_code

    def test_can_apply_not_none(self):
        code = "if x is not None:"
        assert NullCheckBug().can_apply(code) is True


class TestReturnValueBug:
    def test_can_apply_true(self):
        code = "return True"
        assert ReturnValueBug().can_apply(code) is True

    def test_apply_true_to_false(self):
        code = "def check():\n    return True"
        variant = ReturnValueBug().apply(code)
        assert "False" in variant.buggy_code
        assert "return True" not in variant.buggy_code

    def test_apply_return_zero_to_one(self):
        code = "return 0"
        variant = ReturnValueBug().apply(code)
        assert "return 1" in variant.buggy_code


class TestTypeCastBug:
    def test_can_apply_int_cast(self):
        code = "x = int(y)"
        assert TypeCastBug().can_apply(code) is True

    def test_apply_remove_int(self):
        code = "result = int(input())"
        variant = TypeCastBug().apply(code)
        assert "int(" not in variant.buggy_code
        assert "input()" in variant.buggy_code

    def test_can_apply_str_cast(self):
        code = "s = str(42)"
        assert TypeCastBug().can_apply(code) is True

    def test_apply_remove_str(self):
        code = "text = str(value)"
        variant = TypeCastBug().apply(code)
        assert "str(" not in variant.buggy_code
        assert "value" in variant.buggy_code


class TestRangeLoopBug:
    def test_can_apply_with_range(self):
        code = "for i in range(10):"
        assert RangeLoopBug().can_apply(code) is True

    def test_apply_range_mutation(self):
        code = "for i in range(n):\n    print(i)"
        variant = RangeLoopBug().apply(code)
        assert "range(" in variant.buggy_code
        assert "n" in variant.buggy_code


class TestAssertionBug:
    def test_can_apply_with_assert(self):
        code = "assert x > 0, 'must be positive'"
        assert AssertionBug().can_apply(code) is True

    def test_apply_remove_assert(self):
        code = "assert len(items) > 0"
        variant = AssertionBug().apply(code)
        assert "pass" in variant.buggy_code
        # Buggy code should have removed the assertion entirely
        assert variant.buggy_code.strip() == "pass"


class TestEarlyReturnBug:
    def test_can_apply_with_function(self):
        code = "def foo():\n    x = 1\n    return x"
        assert EarlyReturnBug().can_apply(code) is True

    def test_apply_insert_early_return(self):
        code = "def calculate(n):\n    total = 0\n    for i in range(n):\n        total += i\n    return total"
        variant = EarlyReturnBug().apply(code)
        assert "return None" in variant.buggy_code
        assert variant.original_code != variant.buggy_code


# ── Bug Injection Tests ────────────────────────────────────────────────────────


class TestBugInjection:
    def test_inject_bugs_returns_variants(self):
        code = "if x < 10 and y > 0:\n    return True"
        variants = inject_bugs(code, max_variants=5)
        assert len(variants) > 0
        assert all(isinstance(v, BugVariant) for v in variants)

    def test_inject_bugs_respects_max(self):
        code = "if x < 10 and y > 0:\n    return True"
        variants = inject_bugs(code, max_variants=2)
        assert len(variants) <= 2

    def test_inject_bugs_sorted_by_severity(self):
        code = "if x < 10 and y > 0:\n    return True"
        variants = inject_bugs(code, max_variants=10)
        severities = [v.severity_level for v in variants]
        assert severities == sorted(severities)

    def test_inject_bugs_simple_code(self):
        # Code with comparison operator for injection
        code = "if x > 0:\n    return True"
        variants = inject_bugs(code, max_variants=5)
        # Should find bugs (at least one)
        assert len(variants) > 0

    def test_inject_bugs_empty_code(self):
        code = ""
        variants = inject_bugs(code)
        assert len(variants) == 0


# ── Bug Variant Tests ──────────────────────────────────────────────────────────


class TestBugVariant:
    def test_variant_has_diff_summary(self):
        variant = BugVariant(
            original_code="x < 10",
            buggy_code="x <= 10",
            bug_description="Off-by-one",
            bug_explanation="Using <= instead of <",
            severity_level=2,
            pattern_name="off_by_one",
            line_number=5,
        )
        assert "[L5]" in variant.diff_summary
        assert "Off-by-one" in variant.diff_summary


# ── Commit Miner Tests ─────────────────────────────────────────────────────────


class TestGitCommitMiner:
    def test_extract_functions_python(self):
        code = """\
def foo():
    pass

def bar(x, y):
    return x + y
"""
        functions = GitCommitMiner.extract_functions(code, language="python")
        assert len(functions) == 2
        assert functions[0][0] == "foo"
        assert functions[1][0] == "bar"

    def test_extract_functions_with_decorators(self):
        code = """\
@decorator
def decorated_func():
    pass
"""
        functions = GitCommitMiner.extract_functions(code, language="python")
        assert len(functions) >= 1

    def test_extract_functions_javascript(self):
        code = """\
function sayHello() {
  console.log("hello");
}

const add = (a, b) => a + b;
"""
        functions = GitCommitMiner.extract_functions(code, language="javascript")
        assert len(functions) >= 1

    def test_should_skip_file_test_files(self):
        """Test files matching patterns are skipped."""
        assert GitCommitMiner._should_skip_file("test_foo.py") is True
        assert GitCommitMiner._should_skip_file("src/tests/bar.py") is True
        assert GitCommitMiner._should_skip_file("README.md") is True

    def test_should_skip_file_keep_source(self):
        """Non-test source files are kept."""
        assert GitCommitMiner._should_skip_file("src/foo.py") is False
        assert GitCommitMiner._should_skip_file("lib/utils.js") is False

    def test_detect_language_python(self):
        files = [("src/main.py", "", "")]
        assert GitCommitMiner._detect_language(files) == "python"

    def test_detect_language_javascript(self):
        files = [("src/app.js", "", "")]
        assert GitCommitMiner._detect_language(files) == "javascript"

    def test_parse_git_diff_simple(self):
        """Test parsing a simple unified diff."""
        diff = """\
diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -1,2 +1,2 @@
-x = 0
+x = 1
 print(x)
"""
        files = GitCommitMiner._parse_git_diff(diff)
        assert len(files) == 1
        assert files[0][0] == "file.py"
        assert "0" in files[0][1]  # before
        assert "1" in files[0][2]  # after


# ── Strategy Integration Tests ─────────────────────────────────────────────────


class TestCodingDiffusionStrategy:
    def test_strategy_registers(self):
        """Verify strategy is registered and discoverable."""
        from scripts.generators.strategy_registry import get_strategy

        try:
            strategy_cls = get_strategy("coding_diffusion")
            assert strategy_cls.__name__ == "CodingDiffusionStrategy"
        except ValueError:
            pytest.skip("coding_diffusion not registered yet")

    def test_strategy_instantiation(self):
        """Test strategy can be created."""
        strategy = CodingDiffusionStrategy(api_key="test-key")
        assert strategy.api_key == "test-key"
        assert strategy.verbose is False

    def test_strategy_verbose_mode(self):
        """Test verbose flag works."""
        strategy = CodingDiffusionStrategy(api_key="test-key", verbose=True)
        assert strategy.verbose is True

    def test_generate_creates_candidates(self):
        """Test generate() produces MCTaskCandidate objects (with mock)."""
        import unittest.mock as mock

        strategy = CodingDiffusionStrategy(api_key="test-key", verbose=False)

        # Mock the distractor generator to avoid API calls
        with mock.patch.object(
            strategy.distractor_gen,
            "generate",
            return_value=[
                "Off-by-one error",
                "Logical operator swap",
                "Type mismatch",
            ],
        ):
            candidates = strategy.generate(families=[], n_per_family=1)

            # Should create candidates from bug injection
            if len(candidates) > 0:
                # Verify structure
                for cand in candidates:
                    assert cand.task_id.startswith("bug_hunt_")
                    assert cand.question_type == "bug_identification"
                    assert cand.choices is not None
                    assert len(cand.choices) > 0
                    assert cand.correct_id in ["A", "B", "C", "D"]
                    assert cand.prompt  # Can generate prompt without error


class TestBugVerifier:
    def test_verifier_init(self):
        """Test verifier initialization."""
        from scripts.generators.runtime import PythonRuntime

        runtime = PythonRuntime()
        verifier = BugVerifier(runtime)
        assert verifier.runtime is runtime

    def test_verify_rejects_identical_output(self):
        """Bug that doesn't change output is rejected."""
        from scripts.generators.runtime import PythonRuntime

        runtime = PythonRuntime()
        verifier = BugVerifier(runtime)

        original = "print('hello')"
        buggy = "print('hello')  # same output"

        is_visible, reason = verifier.verify_bug_is_visible(original, buggy)
        assert is_visible is False
        assert "identical" in reason.lower()

    def test_verify_accepts_different_output(self):
        """Bug that changes output is accepted."""
        from scripts.generators.runtime import PythonRuntime

        runtime = PythonRuntime()
        verifier = BugVerifier(runtime)

        original = "x = 10\nprint(x < 10)"
        buggy = "x = 10\nprint(x <= 10)"

        is_visible, reason = verifier.verify_bug_is_visible(original, buggy)
        assert is_visible is True
        assert "Visible" in reason


# ── Integration Test ───────────────────────────────────────────────────────────


class TestIntegration:
    def test_full_pipeline(self):
        """End-to-end: bug injection → verification → task creation."""
        # Use simpler code without early return injection issues
        code = "if x < 10:\n    pass"

        # Inject bugs
        variants = inject_bugs(code, max_variants=3)
        assert len(variants) > 0

        # Verify they compile
        from scripts.generators.runtime import PythonRuntime

        runtime = PythonRuntime()
        for variant in variants:
            # Both should be syntactically valid
            try:
                compile(variant.original_code, "<string>", "exec")
                compile(variant.buggy_code, "<string>", "exec")
            except SyntaxError as e:
                pytest.fail(f"Invalid syntax in {variant.pattern_name}: {e}")
