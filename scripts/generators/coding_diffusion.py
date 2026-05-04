"""Coding Diffusion: Bug-finding benchmark generation from repository commits.

Strategy Overview:
  1. Mine recent commits from a GitHub repo
  2. Extract modified functions/snippets
  3. Inject subtle bugs via pattern library
  4. Verify bugs are visible (output differs from original)
  5. Generate multi-choice questions asking agents to identify bugs
  6. Quality-filter confounders via Guide scorer

This is a fourth generation benchmark strategy, complementing:
  - Adversarial: Rule overgeneralization
  - Knowledge: Direct behavioral prediction
  - SGS: Adversarial + quality filtering

Tasks test:
  - Code reading comprehension
  - Bug detection across subtle interactions
  - Reasoning about root causes
  - Handling version-specific/environment bugs

Usage:
    from scripts.generators.coding_diffusion import CodingDiffusionStrategy
    from scripts.generators.runtime import make_runtime

    strategy = CodingDiffusionStrategy(api_key="sk-ant-...")
    candidates = strategy.generate(families=families, n_per_family=3)
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import anthropic

from scripts.generators.bug_patterns import BugVariant, inject_bugs
from scripts.generators.pandas_mc import MCTaskCandidate
from scripts.generators.runtime import ExecutionRuntime, PythonRuntime
from scripts.generators.strategy_registry import GenerationStrategy, register_strategy


@dataclass
class Commit:
    """Git commit metadata."""

    hash: str
    message: str
    author: str
    timestamp: str
    files_changed: list[tuple[str, str, str]]  # (filepath, before, after)
    language: str = "python"


class GitCommitMiner:
    """Mine recent commits from a GitHub repository."""

    # File patterns to skip
    SKIP_PATTERNS = [
        r"test", r"spec", r"docs?", r"readme", r"\.md$", r"\.txt$",
        r"build/", r"dist/", r"\.egg", r"__pycache__", r"\.pyc",
    ]

    @staticmethod
    def fetch_commits(
        repo_url: str,
        k: int = 10,
        filter_test_files: bool = True,
    ) -> list[Commit]:
        """Fetch last K commits from a repo via git.

        Args:
            repo_url: GitHub URL (https://github.com/owner/repo)
            k: Number of recent commits to fetch
            filter_test_files: Skip test/ docs/ etc.

        Returns:
            list[Commit]: Structured commit objects with diffs
        """
        commits: list[Commit] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir) / "repo"

            try:
                # Clone repo with limited depth for speed
                subprocess.run(
                    ["git", "clone", "--depth", str(k), repo_url, str(repo_path)],
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                if os.getenv("VERBOSE"):
                    print(f"[GitCommitMiner] Clone failed: {e}")
                return commits

            # Get last K commits
            try:
                result = subprocess.run(
                    ["git", "log", "--oneline", f"-{k}"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                )
            except subprocess.CalledProcessError:
                return commits

            commit_hashes = [line.split()[0] for line in result.stdout.strip().split("\n") if line.strip()]

            # Extract each commit
            for commit_hash in commit_hashes:
                try:
                    # Get commit metadata
                    meta_result = subprocess.run(
                        ["git", "log", "-1", "--format=%an%n%ai%n%s", commit_hash],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=True,
                    )
                    lines = meta_result.stdout.strip().split("\n")
                    author = lines[0] if len(lines) > 0 else "Unknown"
                    timestamp = lines[1] if len(lines) > 1 else ""
                    message = lines[2] if len(lines) > 2 else ""

                    # Get diff
                    diff_result = subprocess.run(
                        ["git", "show", "--format=", commit_hash],
                        cwd=repo_path,
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=True,
                    )

                    # Parse diff
                    files_changed = GitCommitMiner._parse_git_diff(diff_result.stdout)

                    # Filter if needed
                    if filter_test_files:
                        files_changed = [
                            f
                            for f in files_changed
                            if not GitCommitMiner._should_skip_file(f[0])
                        ]

                    if files_changed:
                        commit = Commit(
                            hash=commit_hash,
                            message=message,
                            author=author,
                            timestamp=timestamp,
                            files_changed=files_changed,
                            language=GitCommitMiner._detect_language(files_changed),
                        )
                        commits.append(commit)

                except subprocess.CalledProcessError:
                    continue

        return commits

    @staticmethod
    def _should_skip_file(filepath: str) -> bool:
        """Check if file should be skipped."""
        lower = filepath.lower()
        return any(re.search(pattern, lower, re.IGNORECASE) for pattern in GitCommitMiner.SKIP_PATTERNS)

    @staticmethod
    def _detect_language(files_changed: list) -> str:
        """Detect language from file extensions."""
        for filepath, _, _ in files_changed:
            if filepath.endswith(".py"):
                return "python"
            elif filepath.endswith((".js", ".ts", ".jsx", ".tsx")):
                return "javascript"
            elif filepath.endswith((".go",)):
                return "go"
        return "python"

    @staticmethod
    def _parse_git_diff(diff_text: str) -> list[tuple[str, str, str]]:
        """Parse unified diff into (filepath, before, after) tuples.

        Extracts actual code before/after for small diffs only (< 1000 lines).
        """
        files_changed: list[tuple[str, str, str]] = []
        
        current_file = None
        current_before = []
        current_after = []
        in_hunk = False
        
        for line in diff_text.split("\n"):
            if line.startswith("diff --git"):
                # Save previous file
                if current_file and (current_before or current_after):
                    files_changed.append((
                        current_file,
                        "\n".join(current_before),
                        "\n".join(current_after),
                    ))
                current_file = None
                current_before = []
                current_after = []
                
            elif line.startswith("+++"):
                # Extract filename
                parts = line.split("\t")
                if len(parts) > 0:
                    current_file = parts[0][6:]  # Remove "b/" prefix
                in_hunk = False
                
            elif line.startswith("@@"):
                in_hunk = True
                
            elif in_hunk:
                if line.startswith("-") and not line.startswith("---"):
                    current_before.append(line[1:])
                elif line.startswith("+") and not line.startswith("+++"):
                    current_after.append(line[1:])
        
        # Save last file
        if current_file and (current_before or current_after):
            files_changed.append((
                current_file,
                "\n".join(current_before),
                "\n".join(current_after),
            ))
        
        return files_changed

    @staticmethod
    def extract_functions(code: str, language: str = "python") -> list[Tuple[str, int]]:
        """Extract function definitions from code.

        Args:
            code: Source code
            language: Language (python, javascript, go)

        Returns:
            list of (function_name, start_line)
        """
        functions: list[Tuple[str, int]] = []

        if language == "python":
            for i, line in enumerate(code.split("\n"), 1):
                if re.match(r"^\s*def\s+(\w+)\s*\(", line):
                    match = re.search(r"def\s+(\w+)\s*\(", line)
                    if match:
                        functions.append((match.group(1), i))

        elif language == "javascript":
            for i, line in enumerate(code.split("\n"), 1):
                if re.match(r"^\s*(function\s+\w+|const\s+\w+\s*=\s*(async\s+)?\()", line):
                    match = re.search(r"(function\s+|const\s+)(\w+)", line)
                    if match:
                        functions.append((match.group(2), i))

        return functions


@dataclass
class BugTaskCandidate:
    """Bug-finding task before conversion to MCTaskCandidate."""

    task_id: str
    commit_hash: str
    function_name: str
    original_code: str
    buggy_code: str
    bug_variant: BugVariant
    difficulty: int  # 1-5 based on severity


class BugVerifier:
    """Verify that injected bugs are visible and non-trivial."""

    def __init__(self, runtime: ExecutionRuntime):
        self.runtime = runtime

    def verify_bug_is_visible(
        self,
        original_code: str,
        buggy_code: str,
        test_code: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Check if bug produces different output.

        Args:
            original_code: Original, correct code
            buggy_code: Code with injected bug
            test_code: Optional test to verify against

        Returns:
            (is_visible, reason): Whether bug is visible and why
        """
        # Run both snippets
        ok_orig, out_orig = self.runtime.run(original_code, timeout=5)
        ok_buggy, out_buggy = self.runtime.run(buggy_code, timeout=5)

        # Reject if syntax/import error (too trivial)
        if not ok_orig or not ok_buggy:
            return (
                False,
                f"Syntax/import error: original={ok_orig}, buggy={ok_buggy}",
            )

        # Reject if outputs match (bug not visible)
        if out_orig == out_buggy:
            return False, f"Outputs identical: {out_orig!r}"

        # Accept: bug is visible
        return (
            True,
            f"Visible: {out_orig!r} → {out_buggy!r}",
        )


class DistractorGenerator:
    """Generate plausible wrong bug descriptions."""

    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-20241022"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def generate(
        self,
        correct_bug: BugVariant,
        original_code: str,
        buggy_code: str,
    ) -> list[str]:
        """Generate 3 plausible wrong answers + 1 correct.

        Args:
            correct_bug: The actual bug
            original_code: Original snippet
            buggy_code: Code with bug

        Returns:
            [correct_description, wrong1, wrong2, wrong3]
        """
        prompt = f"""\
Analyze this buggy code and generate plausible alternative bug descriptions.

ORIGINAL CODE:
```python
{original_code}
```

BUGGY CODE:
```python
{buggy_code}
```

ACTUAL BUG (correct answer):
{correct_bug.bug_description}

Generate 3 PLAUSIBLE WRONG answers that:
1. Sound superficially correct but describe a different bug
2. Could trick someone reading the code quickly
3. Are NOT syntax/import errors
4. Are specific to this code change

Format: Return ONLY 3 lines, one wrong description per line."""

        msg = self.client.messages.create(
            model=self.model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        text = msg.content[0].text.strip()
        wrong_answers = [line.strip() for line in text.split("\n") if line.strip()][:3]

        # Return [correct, wrong1, wrong2, wrong3]
        return [correct_bug.bug_description] + wrong_answers


@register_strategy("coding_diffusion")
class CodingDiffusionStrategy(GenerationStrategy):
    """Bug-finding benchmark generation from repository commits.

    Mines recent commits, injects subtle bugs, and creates multi-choice
    questions asking agents to identify the bugs.

    Families are ignored; this strategy extracts code from repo commits instead.
    """

    def __init__(self, api_key: str, verbose: bool = False, seed: int | None = None):
        self.api_key = api_key
        self.verbose = verbose
        self.seed = seed
        self.client = anthropic.Anthropic(api_key=api_key)
        self.runtime = PythonRuntime(install="pip install -q pandas scikit-learn")
        self.verifier = BugVerifier(self.runtime)
        self.distractor_gen = DistractorGenerator(api_key=api_key)

    def generate(
        self,
        families: list[dict],
        n_per_family: int = 3,
    ) -> list[MCTaskCandidate]:
        """Generate bug-finding tasks.

        Args:
            families: (Ignored for this strategy; uses repo commits instead)
            n_per_family: Target tasks per family

        Returns:
            list[MCTaskCandidate]: Bug-finding multi-choice tasks
        """
        if self.verbose:
            print("[coding_diffusion] Starting generation (Phase 1: No real mining yet)")

        candidates: list[MCTaskCandidate] = []

        # For Phase 1, generate synthetic examples without real commits
        # Phase 2 will implement GitCommitMiner.fetch_commits()

        # Create demo task with actual code + injected bug
        demo_code = """\
def calculate_average(numbers):
    total = sum(numbers)
    count = len(numbers)
    if count <= 0:
        return None
    return total / count
"""

        # Generate bugs from simple test codes
        test_snippets = [
            "if x < 10:\n    pass",
            "return True",
            "x = items[0]",
            "if value is None:\n    pass",
        ]

        task_counter = 0
        for snippet_idx, code_snippet in enumerate(test_snippets):
            variants = inject_bugs(code_snippet, max_variants=n_per_family)
            if self.verbose:
                print(
                    f"[coding_diffusion] Generated {len(variants)} variants from snippet {snippet_idx}"
                )

            # Verify and convert to tasks
            for i, variant in enumerate(variants):
                try:
                    is_visible, reason = self.verifier.verify_bug_is_visible(
                        variant.original_code,
                        variant.buggy_code,
                    )

                    if not is_visible:
                        if self.verbose:
                            print(f"[coding_diffusion] Rejected variant: {reason}")
                        continue

                    # Generate distractors
                    distractors = self.distractor_gen.generate(
                        variant,
                        variant.original_code,
                        variant.buggy_code,
                    )

                    # Create MCTaskCandidate
                    task_id = f"bug_hunt_demo_{task_counter:02d}"
                    task_counter += 1

                    choices = [
                        {"id": chr(65 + j), "text": text, "type": "bug_description"}
                        for j, text in enumerate(distractors)
                    ]

                    candidate = MCTaskCandidate(
                        task_id=task_id,
                        question_type="bug_identification",
                        family="code_bugs_synthetic",
                        difficulty=min(5, variant.severity_level + 2),
                        description=f"Find the bug: {variant.bug_description}",
                        is_hard_negative=False,
                        curriculum_note=f"Bug pattern: {variant.pattern_name}, Level {variant.severity_level}",
                        source_excerpt=variant.original_code,
                        proposed_change=f"Code changed (buggy modification at line {variant.line_number})",
                        snippet=variant.buggy_code,
                        question_stem="Identify the bug in this code. Which description is correct?",
                        choices=choices,
                        correct_id="A",  # First choice is always correct
                        explanation=variant.bug_explanation,
                        metadata={
                            "library_name": "synthetic",
                            "pattern": variant.pattern_name,
                            "severity_level": variant.severity_level,
                            "verification": reason,
                        },
                    )

                    candidates.append(candidate)
                    if self.verbose:
                        print(f"[coding_diffusion] Created task: {task_id}")

                except Exception as e:
                    if self.verbose:
                        print(f"[coding_diffusion] Error processing variant: {e}")
                    continue

        if self.verbose:
            print(f"[coding_diffusion] Generated {len(candidates)} tasks total")

        return candidates
