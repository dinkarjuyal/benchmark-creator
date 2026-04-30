"""Language-agnostic execution runtimes for snippet verification.

Each runtime executes a short code snippet and returns (success, output).
The two-player adversarial game uses a runtime to verify:
  - Player 1's confirming snippet produces the expected output
  - Player 2's confounder snippet produces a *different* output

Adding a new language:
  1. Subclass ExecutionRuntime
  2. Implement run() and setup_hint()
  3. Register in make_runtime()

Usage:
    from scripts.generators.runtime import make_runtime

    rt = make_runtime("javascript", install="npm install lodash")
    ok, out = rt.run("import _ from 'lodash'; console.log(_.chunk([1,2,3,4], 2).length)")
    # → (True, "2")
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod


class ExecutionRuntime(ABC):
    """Interface for executing code snippets in any language.

    Implementations handle subprocess management, timeout enforcement,
    and error normalisation. All return (success: bool, output: str)
    where output is stripped stdout on success or an error string prefixed
    with "ERROR:" on failure.
    """

    @abstractmethod
    def run(self, snippet: str, timeout: int = 10) -> tuple[bool, str]:
        """Execute snippet. Returns (success, stdout_or_error)."""
        ...

    @abstractmethod
    def setup_hint(self) -> str:
        """Human-readable install line for Player 1 prompt context.

        E.g. "pip install pandas" or "npm install lodash".
        """
        ...

    @property
    def language(self) -> str:
        """Language name used in LLM prompts and SFT export."""
        return "unknown"


# ── Python ────────────────────────────────────────────────────────────────────

class PythonRuntime(ExecutionRuntime):
    """Runs snippets via a configurable Python executable (default: sys.executable).

    Pass ``python_bin`` to override, e.g. ``"uv run --with torch python3"`` for
    snippets that require torch without a local installation.
    """

    def __init__(self, install: str = "", python_bin: str | None = None):
        self._install = install
        # Support shell-style strings like "uv run --with torch python3"
        if python_bin:
            self._cmd = python_bin.split() if isinstance(python_bin, str) else python_bin
        else:
            self._cmd = [sys.executable]

    def run(self, snippet: str, timeout: int = 10) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                self._cmd + ["-c", snippet],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"ERROR: timed out after {timeout}s"
        if result.returncode != 0:
            return False, f"ERROR: {result.stderr.strip()[:200]}"
        return True, result.stdout.strip()

    def setup_hint(self) -> str:
        return self._install or "pip install <library>"

    @property
    def language(self) -> str:
        return "python"


# ── JavaScript / Node ─────────────────────────────────────────────────────────

class NodeRuntime(ExecutionRuntime):
    """Runs ES module snippets via `node --input-type=module`.

    Snippets should use `console.log(...)` to produce output.
    CommonJS `require()` is NOT available — use ES module imports instead:
        import _ from 'lodash';
    """

    def run(self, snippet: str, timeout: int = 10) -> tuple[bool, str]:
        if not shutil.which("node"):
            return False, "ERROR: node not found in PATH"
        try:
            result = subprocess.run(
                ["node", "--input-type=module"],
                input=snippet,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"ERROR: timed out after {timeout}s"
        if result.returncode != 0:
            return False, f"ERROR: {result.stderr.strip()[:200]}"
        return True, result.stdout.strip()

    def setup_hint(self) -> str:
        return "npm install <library>"

    @property
    def language(self) -> str:
        return "javascript"


# ── Go ────────────────────────────────────────────────────────────────────────

class GoRuntime(ExecutionRuntime):
    """Runs Go snippets via `go run`.

    If the snippet does not contain `func main()`, it is wrapped in a
    minimal main package so bare statement blocks can be tested directly.
    """

    def run(self, snippet: str, timeout: int = 15) -> tuple[bool, str]:
        if not shutil.which("go"):
            return False, "ERROR: go not found in PATH"

        if "func main()" not in snippet:
            snippet = (
                'package main\n'
                'import "fmt"\n'
                'func main() {\n'
                f'{snippet}\n'
                '_ = fmt.Sprintf  // suppress unused import\n'
                '}'
            )

        tmpfile = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".go", mode="w", delete=False
            ) as f:
                f.write(snippet)
                tmpfile = f.name

            result = subprocess.run(
                ["go", "run", tmpfile],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                return False, f"ERROR: {result.stderr.strip()[:200]}"
            return True, result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, f"ERROR: timed out after {timeout}s"
        finally:
            if tmpfile and os.path.exists(tmpfile):
                os.unlink(tmpfile)

    def setup_hint(self) -> str:
        return "go get <module>"

    @property
    def language(self) -> str:
        return "go"


# ── Language detection ────────────────────────────────────────────────────────

def detect_language(
    repo_url: str = "",
    families: list[dict] | None = None,
) -> str:
    """Infer language from a GitHub URL or family install hints.

    Priority:
      1. URL keyword heuristics (fast, no network)
      2. `install` field of first family (covers non-obvious repos)
      3. Default: "python"

    This is intentionally simple — the user can always override with
    `--language` on the CLI.
    """
    url = (repo_url or "").lower()

    if url:
        if any(k in url for k in ("nodejs", "typescript", "/npm/", "vercel", "nextjs")):
            return "javascript"
        if any(k in url for k in ("/go/", "-golang", ".go.", "golang")):
            return "go"
        if any(k in url for k in ("/rust", "crates.io", "-rs", ".rs.")):
            return "rust"
        if "rubygems" in url or "/ruby/" in url:
            return "ruby"
        if "/java/" in url or "maven" in url or "gradle" in url:
            return "java"

    if families:
        install = (families[0].get("install") or "").lower()
        if "npm" in install or "yarn" in install or "pnpm" in install:
            return "javascript"
        if "go get" in install or "go install" in install:
            return "go"
        if "cargo" in install:
            return "rust"
        if "gem install" in install or "bundle" in install:
            return "ruby"
        if "mvn" in install or "gradle" in install:
            return "java"

    return "python"


# ── Factory ───────────────────────────────────────────────────────────────────

def make_runtime(language: str, install: str = "",
                 python_bin: str | None = None) -> ExecutionRuntime:
    """Return the appropriate ExecutionRuntime for a language name.

    Falls back to PythonRuntime for unrecognised languages (safe default,
    allows gradual rollout of new runtimes).
    """
    _RUNTIMES: dict[str, type[ExecutionRuntime]] = {
        "python":     PythonRuntime,
        "javascript": NodeRuntime,
        "typescript": NodeRuntime,
        "go":         GoRuntime,
    }
    cls = _RUNTIMES.get(language.lower(), PythonRuntime)
    if cls is PythonRuntime:
        return PythonRuntime(install=install, python_bin=python_bin)
    return cls()
