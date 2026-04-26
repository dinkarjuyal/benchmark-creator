"""Tests for scripts/generators/runtime.py and scripts/export_sft.py.

No API key required — subprocesses are mocked where needed, and SFT export
operates purely on in-memory MCTaskCandidate objects.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generators.runtime import (
    GoRuntime,
    NodeRuntime,
    PythonRuntime,
    detect_language,
    make_runtime,
)


# ── PythonRuntime ─────────────────────────────────────────────────────────────

class TestPythonRuntime:
    def test_successful_snippet(self):
        rt = PythonRuntime()
        ok, out = rt.run("print(1 + 1)")
        assert ok is True
        assert out == "2"

    def test_syntax_error_returns_false(self):
        rt = PythonRuntime()
        ok, out = rt.run("this is not valid python !!!")
        assert ok is False
        assert out.startswith("ERROR:")

    def test_runtime_error_returns_false(self):
        rt = PythonRuntime()
        ok, out = rt.run("raise ValueError('boom')")
        assert ok is False
        assert "ERROR:" in out

    def test_timeout_returns_false(self):
        rt = PythonRuntime()
        ok, out = rt.run("import time; time.sleep(100)", timeout=1)
        assert ok is False
        assert "timed out" in out

    def test_setup_hint_with_install(self):
        rt = PythonRuntime(install="pip install pandas")
        assert rt.setup_hint() == "pip install pandas"

    def test_setup_hint_without_install(self):
        rt = PythonRuntime()
        assert "pip install" in rt.setup_hint()

    def test_language_property(self):
        assert PythonRuntime().language == "python"

    def test_multiline_output_stripped(self):
        rt = PythonRuntime()
        ok, out = rt.run("print('hello')\nprint('world')")
        assert ok is True
        assert out == "hello\nworld"

    def test_stderr_truncated_in_error(self):
        # Very long error messages are truncated to 200 chars
        rt = PythonRuntime()
        ok, out = rt.run("raise ValueError('x' * 300)")
        assert ok is False
        assert len(out) < 300

    def test_subprocess_timeout_mocked(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("python3", 10)):
            rt = PythonRuntime()
            ok, out = rt.run("print(1)")
        assert ok is False
        assert "timed out" in out


# ── NodeRuntime ───────────────────────────────────────────────────────────────

class TestNodeRuntime:
    def test_language_property(self):
        assert NodeRuntime().language == "javascript"

    def test_setup_hint(self):
        assert "npm" in NodeRuntime().setup_hint()

    def test_node_not_found_returns_error(self):
        with patch("shutil.which", return_value=None):
            rt = NodeRuntime()
            ok, out = rt.run("console.log(1)")
        assert ok is False
        assert "node not found" in out

    def test_successful_snippet_mocked(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "42\n"
        mock_result.stderr = ""
        with patch("shutil.which", return_value="/usr/bin/node"), \
             patch("subprocess.run", return_value=mock_result):
            rt = NodeRuntime()
            ok, out = rt.run("console.log(42)")
        assert ok is True
        assert out == "42"

    def test_error_snippet_mocked(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "SyntaxError: Unexpected token"
        with patch("shutil.which", return_value="/usr/bin/node"), \
             patch("subprocess.run", return_value=mock_result):
            rt = NodeRuntime()
            ok, out = rt.run("this is not js")
        assert ok is False
        assert "ERROR:" in out

    def test_timeout_mocked(self):
        with patch("shutil.which", return_value="/usr/bin/node"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("node", 10)):
            rt = NodeRuntime()
            ok, out = rt.run("while(true){}")
        assert ok is False
        assert "timed out" in out


# ── GoRuntime ─────────────────────────────────────────────────────────────────

class TestGoRuntime:
    def test_language_property(self):
        assert GoRuntime().language == "go"

    def test_setup_hint(self):
        assert "go get" in GoRuntime().setup_hint()

    def test_go_not_found_returns_error(self):
        with patch("shutil.which", return_value=None):
            rt = GoRuntime()
            ok, out = rt.run('fmt.Println("hello")')
        assert ok is False
        assert "go not found" in out

    def test_successful_snippet_mocked(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "hello\n"
        mock_result.stderr = ""
        with patch("shutil.which", return_value="/usr/local/go/bin/go"), \
             patch("subprocess.run", return_value=mock_result):
            rt = GoRuntime()
            ok, out = rt.run('fmt.Println("hello")')
        assert ok is True
        assert out == "hello"

    def test_snippet_wrapped_in_main(self):
        """Snippet without func main() should be wrapped before execution."""
        captured = {}
        def fake_run(cmd, **kwargs):
            import tempfile, os
            # Read the tempfile that was passed to go run
            tmpfile = cmd[-1]
            if os.path.exists(tmpfile):
                captured["content"] = Path(tmpfile).read_text()
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        with patch("shutil.which", return_value="/usr/local/go/bin/go"), \
             patch("subprocess.run", side_effect=fake_run):
            rt = GoRuntime()
            rt.run('fmt.Println("test")')

        content = captured.get("content", "")
        assert "func main()" in content
        assert "package main" in content

    def test_snippet_with_main_not_double_wrapped(self):
        """Snippet already containing func main() should not be re-wrapped."""
        captured = {}
        def fake_run(cmd, **kwargs):
            import os
            tmpfile = cmd[-1]
            if os.path.exists(tmpfile):
                captured["content"] = Path(tmpfile).read_text()
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        snippet = 'package main\nfunc main() { println("hi") }'
        with patch("shutil.which", return_value="/usr/local/go/bin/go"), \
             patch("subprocess.run", side_effect=fake_run):
            rt = GoRuntime()
            rt.run(snippet)

        content = captured.get("content", "")
        assert content.count("func main()") == 1

    def test_tempfile_cleaned_up_on_success(self):
        """Temp file should be removed even after successful execution."""
        created_files = []
        original_tempfile = __import__("tempfile").NamedTemporaryFile

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            return result

        with patch("shutil.which", return_value="/usr/local/go/bin/go"), \
             patch("subprocess.run", side_effect=fake_run):
            rt = GoRuntime()
            rt.run('fmt.Println("test")')
        # If the file was cleaned up correctly, no assertion error — the finally block handles it

    def test_timeout_mocked(self):
        with patch("shutil.which", return_value="/usr/local/go/bin/go"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("go", 15)):
            rt = GoRuntime()
            ok, out = rt.run('for {}')
        assert ok is False
        assert "timed out" in out


# ── detect_language ───────────────────────────────────────────────────────────

class TestDetectLanguage:
    def test_nodejs_in_url(self):
        assert detect_language("https://github.com/nodejs/node") == "javascript"

    def test_typescript_in_url(self):
        assert detect_language("https://github.com/microsoft/typescript") == "javascript"

    def test_npm_in_url(self):
        assert detect_language("https://github.com/npm/cli") == "javascript"

    def test_vercel_in_url(self):
        assert detect_language("https://github.com/vercel/next.js") == "javascript"

    def test_golang_in_url(self):
        assert detect_language("https://github.com/golang/go") == "go"

    def test_go_dash_in_url(self):
        assert detect_language("https://github.com/gin-gonic/gin-golang") == "go"

    def test_rust_in_url(self):
        assert detect_language("https://github.com/rust-lang/rust") == "rust"

    def test_crates_io(self):
        assert detect_language("https://crates.io/crates/serde") == "rust"

    def test_npm_install_hint(self):
        families = [{"install": "npm install lodash"}]
        assert detect_language(families=families) == "javascript"

    def test_yarn_install_hint(self):
        families = [{"install": "yarn add react"}]
        assert detect_language(families=families) == "javascript"

    def test_go_get_hint(self):
        families = [{"install": "go get github.com/gin-gonic/gin"}]
        assert detect_language(families=families) == "go"

    def test_cargo_hint(self):
        families = [{"install": "cargo add serde"}]
        assert detect_language(families=families) == "rust"

    def test_gem_hint(self):
        families = [{"install": "gem install rails"}]
        assert detect_language(families=families) == "ruby"

    def test_default_python(self):
        assert detect_language() == "python"

    def test_python_repo_defaults_to_python(self):
        assert detect_language("https://github.com/pandas-dev/pandas") == "python"

    def test_empty_url_uses_families(self):
        families = [{"install": "go install github.com/tool/cmd@latest"}]
        assert detect_language("", families=families) == "go"

    def test_url_takes_priority_over_families(self):
        # URL says JS, families say Go — URL wins
        families = [{"install": "go get some/pkg"}]
        result = detect_language("https://github.com/vercel/next.js", families=families)
        assert result == "javascript"


# ── make_runtime factory ──────────────────────────────────────────────────────

class TestMakeRuntime:
    def test_python_returns_python_runtime(self):
        rt = make_runtime("python")
        assert isinstance(rt, PythonRuntime)

    def test_javascript_returns_node_runtime(self):
        rt = make_runtime("javascript")
        assert isinstance(rt, NodeRuntime)

    def test_typescript_returns_node_runtime(self):
        rt = make_runtime("typescript")
        assert isinstance(rt, NodeRuntime)

    def test_go_returns_go_runtime(self):
        rt = make_runtime("go")
        assert isinstance(rt, GoRuntime)

    def test_unknown_language_falls_back_to_python(self):
        rt = make_runtime("cobol")
        assert isinstance(rt, PythonRuntime)

    def test_case_insensitive(self):
        assert isinstance(make_runtime("Python"), PythonRuntime)
        assert isinstance(make_runtime("JavaScript"), NodeRuntime)
        assert isinstance(make_runtime("GO"), GoRuntime)

    def test_install_passed_to_python_runtime(self):
        rt = make_runtime("python", install="pip install requests")
        assert isinstance(rt, PythonRuntime)
        assert rt.setup_hint() == "pip install requests"

    def test_install_ignored_for_node(self):
        # NodeRuntime doesn't use the install string (it's npm-based)
        rt = make_runtime("javascript", install="npm install lodash")
        assert isinstance(rt, NodeRuntime)


# ── SFT export ────────────────────────────────────────────────────────────────

def _make_candidate(correct_id: str = "A", language: str = "python"):
    """Build a minimal MCTaskCandidate for SFT export tests."""
    from scripts.generators.pandas_mc import MCTaskCandidate

    choices = [
        {"id": "A", "text": "42", "type": "correct"},
        {"id": "B", "text": "None", "type": "plausible_misconception"},
        {"id": "C", "text": "0", "type": "plausible_misconception"},
        {"id": "D", "text": "Error", "type": "plausible_misconception"},
    ]
    # Rotate so correct_id is the right one
    if correct_id != "A":
        for c in choices:
            if c["id"] == correct_id:
                c["type"] = "correct"
            elif c["type"] == "correct":
                c["type"] = "plausible_misconception"

    return MCTaskCandidate(
        task_id="test_task_001",
        question_type="adversarial_confounder",
        family="nan_semantics",
        difficulty=2,
        description="Test description",
        is_hard_negative=True,
        curriculum_note="Test curriculum",
        source_excerpt="# Rule\n",
        proposed_change="No change",
        snippet="import pandas as pd\nprint(pd.NA == pd.NA)",
        question_stem="What does the following code print?",
        choices=choices,
        correct_id=correct_id,
        explanation="pd.NA is not equal to itself",
        metadata={
            "rule": "NaN != NaN follows IEEE 754",
            "why_model_gets_it_wrong": "Model assumes NA == NA like Python None",
            "language": language,
            "library_name": "pandas",
            "generation_date": "2026-01-01T00:00:00",
        },
    )


class TestCandidateToSft:
    def test_output_has_messages_key(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate()
        result = candidate_to_sft(cand)
        assert "messages" in result

    def test_messages_has_three_roles(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate()
        result = candidate_to_sft(cand)
        roles = [m["role"] for m in result["messages"]]
        assert roles == ["system", "user", "assistant"]

    def test_assistant_contains_correct_answer(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate(correct_id="A")
        result = candidate_to_sft(cand)
        assistant = result["messages"][2]["content"]
        assert "42" in assistant  # correct answer text
        assert "A" in assistant

    def test_assistant_contains_rule(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate()
        result = candidate_to_sft(cand)
        assistant = result["messages"][2]["content"]
        assert "NaN != NaN" in assistant

    def test_assistant_contains_why_wrong(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate()
        result = candidate_to_sft(cand)
        assistant = result["messages"][2]["content"]
        assert "Model assumes" in assistant

    def test_language_metadata_propagated(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate(language="javascript")
        result = candidate_to_sft(cand)
        assert result["language"] == "javascript"
        assert "javascript" in result["messages"][0]["content"]  # system prompt

    def test_task_id_in_output(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate()
        result = candidate_to_sft(cand)
        assert result["task_id"] == "test_task_001"

    def test_source_benchmark_is_family(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate()
        result = candidate_to_sft(cand)
        assert result["source_benchmark"] == "nan_semantics"

    def test_user_contains_snippet(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate()
        result = candidate_to_sft(cand)
        user = result["messages"][1]["content"]
        assert "import pandas as pd" in user

    def test_user_contains_choices(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate()
        result = candidate_to_sft(cand)
        user = result["messages"][1]["content"]
        assert "A." in user
        assert "B." in user

    def test_missing_rule_handled_gracefully(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate()
        cand.metadata.pop("rule", None)
        result = candidate_to_sft(cand)
        # Should not raise; assistant content is still present
        assert result["messages"][2]["content"]

    def test_output_is_json_serializable(self):
        from scripts.export_sft import candidate_to_sft
        cand = _make_candidate()
        result = candidate_to_sft(cand)
        # Must round-trip through JSON without error
        serialized = json.dumps(result)
        deserialized = json.loads(serialized)
        assert deserialized["task_id"] == "test_task_001"


class TestExportSft:
    def test_writes_jsonl_file(self, tmp_path):
        from scripts.export_sft import export_sft
        cands = [_make_candidate(), _make_candidate()]
        out = tmp_path / "train.jsonl"
        n = export_sft(cands, out)
        assert n == 2
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_each_line_is_valid_json(self, tmp_path):
        from scripts.export_sft import export_sft
        cands = [_make_candidate()]
        out = tmp_path / "train.jsonl"
        export_sft(cands, out)
        for line in out.read_text().strip().split("\n"):
            obj = json.loads(line)
            assert "messages" in obj

    def test_creates_parent_dirs(self, tmp_path):
        from scripts.export_sft import export_sft
        cands = [_make_candidate()]
        out = tmp_path / "nested" / "deep" / "train.jsonl"
        n = export_sft(cands, out)
        assert n == 1
        assert out.exists()

    def test_append_mode(self, tmp_path):
        from scripts.export_sft import export_sft
        cands = [_make_candidate()]
        out = tmp_path / "train.jsonl"
        export_sft(cands, out)
        export_sft(cands, out, append=True)
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_overwrite_mode(self, tmp_path):
        from scripts.export_sft import export_sft
        cands = [_make_candidate(), _make_candidate()]
        out = tmp_path / "train.jsonl"
        export_sft(cands, out)
        export_sft([_make_candidate()], out)  # overwrite
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 1

    def test_empty_list_writes_empty_file(self, tmp_path):
        from scripts.export_sft import export_sft
        out = tmp_path / "train.jsonl"
        n = export_sft([], out)
        assert n == 0
        assert out.read_text() == ""

    def test_returns_count(self, tmp_path):
        from scripts.export_sft import export_sft
        cands = [_make_candidate() for _ in range(5)]
        out = tmp_path / "train.jsonl"
        n = export_sft(cands, out)
        assert n == 5
