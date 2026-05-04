"""Bug injection patterns for code-based benchmarks.

This module defines a taxonomy of code mutations that introduce subtle bugs
at varying levels of complexity (1-5). Each pattern is language-agnostic at
the conceptual level, with language-specific implementations provided by
subclasses.

Used by CodingDiffusionStrategy to inject synthetic bugs into repository code
for benchmark task generation.

Bug Levels:
  1 - Direct logic bugs (operator swap, constant mutation)
  2 - Type/boundary bugs (NaN handling, index bounds)
  3 - Interaction bugs (two unrelated changes interact)
  4 - Semantic bugs (correct syntax, wrong intent)
  5 - Subtle architectural bugs (cache, race conditions, contracts)
"""
from __future__ import annotations

import ast
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass
class BugVariant:
    """Single bug injection result."""

    original_code: str
    buggy_code: str
    bug_description: str
    bug_explanation: str
    severity_level: int  # 1-5
    pattern_name: str
    line_number: Optional[int] = None
    changed_tokens: Optional[list[str]] = None

    @property
    def diff_summary(self) -> str:
        """Human-readable summary of what changed."""
        return f"[L{self.line_number}] {self.bug_description}"


# ── Bug Pattern ABC ────────────────────────────────────────────────────────────


class BugPattern(ABC):
    """Base class for code mutation patterns.

    Each pattern defines:
    - Whether it can apply to a code snippet (language-dependent)
    - How to mutate code to introduce the bug
    - The bug description and explanation
    - Severity level (1-5)
    """

    severity_level: int  # Override in subclass
    pattern_name: str  # Override in subclass
    description_template: str  # e.g. "Off-by-one: < should be <="

    @abstractmethod
    def can_apply(self, code: str) -> bool:
        """Check if this pattern can be applied to the snippet."""
        ...

    @abstractmethod
    def apply(self, code: str) -> BugVariant:
        """Apply the mutation. Returns BugVariant or raises ValueError."""
        ...


# ── Python-Specific Patterns ───────────────────────────────────────────────────


class OffByOneBug(BugPattern):
    """Swap comparison operators: < ↔ <=, > ↔ >=, etc."""

    severity_level = 2
    pattern_name = "off_by_one"
    description_template = "Off-by-one: comparison operator mutation"

    PAIRS = [
        ("<", "<="),
        ("<=", "<"),
        (">", ">="),
        (">=", ">"),
    ]

    def can_apply(self, code: str) -> bool:
        """Check if code has at least one comparison operator."""
        return any(op in code for op, _ in self.PAIRS)

    def apply(self, code: str) -> BugVariant:
        """Mutate first comparison operator found."""
        for orig, replacement in self.PAIRS:
            if orig in code:
                buggy = code.replace(orig, replacement, 1)
                line = self._find_line_number(code, orig)
                return BugVariant(
                    original_code=code,
                    buggy_code=buggy,
                    bug_description=f"Comparison changed: {orig} → {replacement}",
                    bug_explanation=f"Off-by-one error: using {replacement} instead of {orig} changes boundary condition.",
                    severity_level=self.severity_level,
                    pattern_name=self.pattern_name,
                    line_number=line,
                    changed_tokens=[orig, replacement],
                )
        raise ValueError("No comparison operators found")

    @staticmethod
    def _find_line_number(code: str, token: str) -> int:
        """Find line number of first token occurrence."""
        for i, line in enumerate(code.split("\n"), 1):
            if token in line:
                return i
        return 1


class LogicalOperatorBug(BugPattern):
    """Swap logical operators: and ↔ or."""

    severity_level = 2
    pattern_name = "logical_operator"
    description_template = "Logical operator mutation: and/or swap"

    PAIRS = [
        (" and ", " or "),
        (" or ", " and "),
    ]

    def can_apply(self, code: str) -> bool:
        return any(op in code for op, _ in self.PAIRS)

    def apply(self, code: str) -> BugVariant:
        """Mutate first logical operator found."""
        for orig, replacement in self.PAIRS:
            if orig in code:
                buggy = code.replace(orig, replacement, 1)
                line = self._find_line_number(code, orig.strip())
                return BugVariant(
                    original_code=code,
                    buggy_code=buggy,
                    bug_description=f"Logic operator changed: {orig.strip()} → {replacement.strip()}",
                    bug_explanation=f"Logical error: using {replacement.strip()} instead of {orig.strip()} inverts condition logic.",
                    severity_level=self.severity_level,
                    pattern_name=self.pattern_name,
                    line_number=line,
                    changed_tokens=[orig.strip(), replacement.strip()],
                )
        raise ValueError("No logical operators found")

    @staticmethod
    def _find_line_number(code: str, token: str) -> int:
        for i, line in enumerate(code.split("\n"), 1):
            if token in line:
                return i
        return 1


class IndexingBug(BugPattern):
    """Mutate list indices: [0]→[1], [-1]→[-2], etc."""

    severity_level = 2
    pattern_name = "indexing"
    description_template = "Array index out of bounds or off-by-one"

    def can_apply(self, code: str) -> bool:
        """Check for list/tuple indexing patterns."""
        return bool(re.search(r"\[\s*[-]?\d+\s*\]", code))

    def apply(self, code: str) -> BugVariant:
        """Mutate first numeric index found."""
        # Find first [n] pattern and increment/decrement
        match = re.search(r"\[(\s*)(-?\d+)(\s*)\]", code)
        if not match:
            raise ValueError("No numeric indices found")

        old_idx = int(match.group(2))
        new_idx = old_idx + 1 if old_idx >= 0 else old_idx - 1
        old_text = match.group(0)
        new_text = f"[{match.group(1)}{new_idx}{match.group(3)}]"
        buggy = code.replace(old_text, new_text, 1)
        line = self._find_line_number(code, old_text)

        return BugVariant(
            original_code=code,
            buggy_code=buggy,
            bug_description=f"Index mutation: {old_idx} → {new_idx}",
            bug_explanation=f"Off-by-one: accessing index {new_idx} instead of {old_idx} retrieves wrong element or causes IndexError.",
            severity_level=self.severity_level,
            pattern_name=self.pattern_name,
            line_number=line,
            changed_tokens=[str(old_idx), str(new_idx)],
        )

    @staticmethod
    def _find_line_number(code: str, pattern: str) -> int:
        for i, line in enumerate(code.split("\n"), 1):
            if pattern in line:
                return i
        return 1


class NullCheckBug(BugPattern):
    """Invert null/None checks: is None ↔ is not None."""

    severity_level = 2
    pattern_name = "null_check"
    description_template = "Null check inverted: is/is not swap"

    PAIRS = [
        ("is None", "is not None"),
        ("is not None", "is None"),
        ("== None", "!= None"),
        ("!= None", "== None"),
    ]

    def can_apply(self, code: str) -> bool:
        return any(op in code for op, _ in self.PAIRS)

    def apply(self, code: str) -> BugVariant:
        """Mutate first None check found."""
        for orig, replacement in self.PAIRS:
            if orig in code:
                buggy = code.replace(orig, replacement, 1)
                line = self._find_line_number(code, orig)
                return BugVariant(
                    original_code=code,
                    buggy_code=buggy,
                    bug_description=f"Null check inverted: {orig} → {replacement}",
                    bug_explanation=f"Logic error: condition is inverted. Using {replacement} instead of {orig} reverses the check.",
                    severity_level=self.severity_level,
                    pattern_name=self.pattern_name,
                    line_number=line,
                    changed_tokens=[orig, replacement],
                )
        raise ValueError("No None checks found")

    @staticmethod
    def _find_line_number(code: str, token: str) -> int:
        for i, line in enumerate(code.split("\n"), 1):
            if token in line:
                return i
        return 1


class ReturnValueBug(BugPattern):
    """Mutate return values: True ↔ False, 0 ↔ 1."""

    severity_level = 2
    pattern_name = "return_value"
    description_template = "Return value mutation"

    PAIRS = [
        ("True", "False"),
        ("False", "True"),
        ("return 0", "return 1"),
        ("return 1", "return 0"),
    ]

    def can_apply(self, code: str) -> bool:
        return any(op in code for op, _ in self.PAIRS)

    def apply(self, code: str) -> BugVariant:
        """Mutate first return value found."""
        for orig, replacement in self.PAIRS:
            if orig in code:
                buggy = code.replace(orig, replacement, 1)
                line = self._find_line_number(code, orig)
                return BugVariant(
                    original_code=code,
                    buggy_code=buggy,
                    bug_description=f"Return value: {orig} → {replacement}",
                    bug_explanation=f"Incorrect output: returning {replacement} instead of {orig}.",
                    severity_level=self.severity_level,
                    pattern_name=self.pattern_name,
                    line_number=line,
                    changed_tokens=[orig, replacement],
                )
        raise ValueError("No return values found")

    @staticmethod
    def _find_line_number(code: str, token: str) -> int:
        for i, line in enumerate(code.split("\n"), 1):
            if token in line:
                return i
        return 1


class TypeCastBug(BugPattern):
    """Remove type casts: int(x) → x, str(x) → x, float(x) → x."""

    severity_level = 2
    pattern_name = "type_cast"
    description_template = "Type cast missing or incorrect"

    CASTS = ["int(", "str(", "float(", "bool(", "list(", "dict("]

    def can_apply(self, code: str) -> bool:
        return any(cast in code for cast in self.CASTS)

    def apply(self, code: str) -> BugVariant:
        """Remove first type cast found."""
        for cast in self.CASTS:
            if cast not in code:
                continue
            # Find the cast and its closing paren
            idx = code.find(cast)
            # Simple heuristic: find matching closing paren
            start = idx + len(cast)
            depth = 1
            end = start
            while end < len(code) and depth > 0:
                if code[end] == "(":
                    depth += 1
                elif code[end] == ")":
                    depth -= 1
                end += 1

            if depth != 0:
                raise ValueError(f"Unmatched parentheses in {cast}")

            # Extract content between cast parens
            inner = code[start : end - 1]
            buggy = code[:idx] + inner + code[end:]
            line = self._find_line_number(code, cast)

            return BugVariant(
                original_code=code,
                buggy_code=buggy,
                bug_description=f"Type cast removed: {cast}...)",
                bug_explanation=f"Type error: cast {cast} was removed, causing implicit type coercion.",
                severity_level=self.severity_level,
                pattern_name=self.pattern_name,
                line_number=line,
                changed_tokens=[cast, ""],
            )

        raise ValueError("No type casts found")

    @staticmethod
    def _find_line_number(code: str, token: str) -> int:
        for i, line in enumerate(code.split("\n"), 1):
            if token in line:
                return i
        return 1


class RangeLoopBug(BugPattern):
    """Mutate range() bounds: range(n) → range(n-1), range(n) → range(1, n), etc."""

    severity_level = 2
    pattern_name = "range_loop"
    description_template = "Loop bounds off-by-one"

    def can_apply(self, code: str) -> bool:
        return "range(" in code

    def apply(self, code: str) -> BugVariant:
        """Mutate first range() found."""
        # Simple regex to find range(n) or range(a, b)
        match = re.search(r"range\(([^)]+)\)", code)
        if not match:
            raise ValueError("No range() calls found")

        args = match.group(1).strip()
        old_text = match.group(0)

        # Try to mutate single-arg range
        if "," not in args:
            try:
                # Handle expressions like "n" or "len(x)"
                if args.isdigit():
                    new_args = str(int(args) - 1)
                elif args.endswith("]") or args.endswith(")"):
                    # Complex expression, append -1
                    new_args = f"{args} - 1"
                else:
                    new_args = f"{args} - 1"

                new_text = f"range({new_args})"
                buggy = code.replace(old_text, new_text, 1)
                line = self._find_line_number(code, old_text)

                return BugVariant(
                    original_code=code,
                    buggy_code=buggy,
                    bug_description=f"Loop bound: range({args}) → range({new_args})",
                    bug_explanation=f"Off-by-one in loop: reduced upper bound from {args} to {new_args}, skipping last iteration.",
                    severity_level=self.severity_level,
                    pattern_name=self.pattern_name,
                    line_number=line,
                    changed_tokens=[args, new_args],
                )
            except Exception:
                raise ValueError(f"Cannot mutate range arguments: {args}")

        raise ValueError("Cannot mutate two-arg range()")

    @staticmethod
    def _find_line_number(code: str, token: str) -> int:
        for i, line in enumerate(code.split("\n"), 1):
            if token in line:
                return i
        return 1


class AssertionBug(BugPattern):
    """Remove or invert assertions/validations."""

    severity_level = 3
    pattern_name = "assertion"
    description_template = "Validation check skipped or inverted"

    def can_apply(self, code: str) -> bool:
        return "assert " in code

    def apply(self, code: str) -> BugVariant:
        """Remove first assert statement found."""
        match = re.search(r"^(\s*)assert\s+([^\n]+)$", code, re.MULTILINE)
        if not match:
            raise ValueError("No assert statements found")

        indent = match.group(1)
        condition = match.group(2)
        old_text = match.group(0)
        # Replace with pass (no comment to avoid mentioning "assert")
        new_text = f"{indent}pass"
        buggy = code.replace(old_text, new_text, 1)
        line = self._find_line_number(code, "assert")

        return BugVariant(
            original_code=code,
            buggy_code=buggy,
            bug_description=f"Assertion removed: assert {condition}",
            bug_explanation=f"Validation skipped: removed assertion that checked {condition}.",
            severity_level=self.severity_level,
            pattern_name=self.pattern_name,
            line_number=line,
            changed_tokens=["assert", "pass"],
        )

    @staticmethod
    def _find_line_number(code: str, token: str) -> int:
        for i, line in enumerate(code.split("\n"), 1):
            if token in line:
                return i
        return 1


class EarlyReturnBug(BugPattern):
    """Add early return that skips logic."""

    severity_level = 3
    pattern_name = "early_return"
    description_template = "Early return skips intended logic"

    def can_apply(self, code: str) -> bool:
        """Check if there's a function definition."""
        return "def " in code

    def apply(self, code: str) -> BugVariant:
        """Inject early return after function signature."""
        lines = code.split("\n")
        def_idx = None
        body_idx = None

        for i, line in enumerate(lines):
            if "def " in line and ":" in line:
                def_idx = i
                # Find first non-empty, non-docstring line after
                for j in range(i + 1, len(lines)):
                    stripped = lines[j].strip()
                    if stripped and not stripped.startswith('"""') and not stripped.startswith("'''"):
                        body_idx = j
                        break
                break

        if def_idx is None or body_idx is None:
            raise ValueError("No function with body found")

        # Get indentation of body
        indent = len(lines[body_idx]) - len(lines[body_idx].lstrip())
        indent_str = " " * indent

        # Insert early return (use same indentation as body)
        lines.insert(body_idx, f"{indent_str}return None")
        buggy = "\n".join(lines)

        return BugVariant(
            original_code=code,
            buggy_code=buggy,
            bug_description="Early return added (skips logic)",
            bug_explanation="Early return: function exits prematurely, skipping all intended logic.",
            severity_level=self.severity_level,
            pattern_name=self.pattern_name,
            line_number=body_idx + 1,
            changed_tokens=["(none)", "return None"],
        )


# ── Pattern Registry ───────────────────────────────────────────────────────────


def get_all_patterns() -> list[type[BugPattern]]:
    """Return list of all available bug patterns."""
    return [
        OffByOneBug,
        LogicalOperatorBug,
        IndexingBug,
        NullCheckBug,
        ReturnValueBug,
        TypeCastBug,
        RangeLoopBug,
        AssertionBug,
        EarlyReturnBug,
    ]


def inject_bugs(code: str, max_variants: int = 5) -> list[BugVariant]:
    """Try all patterns, return successful mutations up to max_variants.

    Args:
        code: Python snippet to mutate
        max_variants: Maximum variants to return

    Returns:
        list[BugVariant]: Successful mutations, sorted by severity (ascending)
    """
    variants: list[BugVariant] = []
    patterns = get_all_patterns()

    for pattern_cls in patterns:
        if len(variants) >= max_variants:
            break

        pattern = pattern_cls()
        try:
            if pattern.can_apply(code):
                variant = pattern.apply(code)
                variants.append(variant)
        except (ValueError, Exception):
            # Pattern doesn't apply or failed; continue
            continue

    return sorted(variants, key=lambda v: v.severity_level)
