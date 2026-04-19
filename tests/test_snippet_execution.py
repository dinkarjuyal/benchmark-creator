"""Tests for _run_snippet — the execution verifier at the heart of the pipeline.

Every confounder passes through this function. Wrong behavior here means
questions with incorrect answers make it into the benchmark silently.
"""
import pytest
from scripts.generators.adversarial_mc import _run_snippet


class TestRunSnippet:
    def test_simple_print(self):
        ok, out = _run_snippet("print('hello')")
        assert ok is True
        assert out == "hello"

    def test_multiline_snippet(self):
        snippet = "x = 1 + 1\nprint(x)"
        ok, out = _run_snippet(snippet)
        assert ok is True
        assert out == "2"

    def test_syntax_error_returns_false(self):
        ok, out = _run_snippet("def broken(:\n    pass")
        assert ok is False
        assert "ERROR" in out

    def test_runtime_error_returns_false(self):
        ok, out = _run_snippet("raise ValueError('boom')")
        assert ok is False
        assert "ERROR" in out

    def test_output_is_stripped(self):
        ok, out = _run_snippet("print('  spaces  ')")
        assert ok is True
        assert out == "spaces"  # stdout.strip() removes surrounding whitespace

    def test_import_pandas_works(self):
        snippet = "import pandas as pd\nprint(pd.__version__[:1])"
        ok, out = _run_snippet(snippet)
        assert ok is True
        assert out.isdigit()  # pandas major version is a digit

    def test_list_output(self):
        ok, out = _run_snippet("print([1, 2, 3])")
        assert ok is True
        assert out == "[1, 2, 3]"

    def test_timeout_kills_infinite_loop(self):
        ok, out = _run_snippet("while True: pass", timeout=1)
        assert ok is False
