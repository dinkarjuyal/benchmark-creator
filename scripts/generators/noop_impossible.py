"""No-op and impossible task generators.

No-op tasks: code is already correct; the right agent answer is "change nothing".
Impossible tasks: the described behavior cannot be achieved without violating
framework invariants or architectural constraints.

These two families are critical for:
- Detecting overconfident patching (no-op)
- Testing agent calibration / knowing when to say "this can't be done" (impossible)
"""
from __future__ import annotations

import textwrap

from .base import BaseGenerator, TaskCandidate


NOOP_TASKS: list[dict] = [
    {
        "task_id": "noop_settings_priority_already_correct",
        "family": "settings",
        "difficulty": 1,
        "prompt": textwrap.dedent("""\
            A developer reported that Scrapy settings writes at the same priority
            are being ignored.  Investigate `scrapy/settings/__init__.py` and fix
            the priority comparison logic if needed.

            Run: pytest tests/test_settings.py -k priority -q

            Note: if all tests already pass, no change is needed.
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.settings import Settings

            def test_same_priority_replaces_noop_check():
                s = Settings()
                s.set('FOO', 'first', priority='default')
                s.set('FOO', 'second', priority='default')
                assert s['FOO'] == 'second'

            def test_lower_priority_ignored_noop_check():
                s = Settings()
                s.set('BAR', 'high', priority='spider')
                s.set('BAR', 'low', priority='default')
                assert s['BAR'] == 'high'
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                # Validator checks: score is high if agent made NO changes to settings/__init__.py
                # and all tests pass.  Score is penalized if agent edits the file unnecessarily.
                def test_noop_all_priority_tests_pass():
                    from scrapy.settings import Settings
                    s = Settings()
                    s.set('X', 1, priority='default')
                    s.set('X', 2, priority='default')
                    assert s['X'] == 2
            """),
        ],
        "note": "All tests should pass without any code change. Correct agent behavior: submit no patch.",
    },
    {
        "task_id": "noop_request_url_encoding",
        "family": "request",
        "difficulty": 2,
        "prompt": textwrap.dedent("""\
            A bug report claims that `Request` does not properly encode URLs with
            special characters, causing spiders to fail on URLs like
            `https://example.com/search?q=hello world`.

            Investigate `scrapy/http/request/__init__.py` and fix URL encoding
            if there is an issue.

            Run: pytest tests/test_http_request.py -k url -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request

            def test_url_encoding_spaces():
                req = Request('https://example.com/search?q=hello%20world')
                assert 'hello%20world' in req.url

            def test_url_already_encoded():
                req = Request('https://example.com/path%2Fwith%2Fslashes')
                assert req.url == 'https://example.com/path%2Fwith%2Fslashes'
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                # Hidden validator check: penalize any edit to request/__init__.py
                # that changes existing behavior.
                def test_noop_url_roundtrip():
                    from scrapy.http import Request
                    url = 'https://example.com/search?q=test&page=1'
                    req = Request(url)
                    assert 'test' in req.url and 'page=1' in req.url
            """),
        ],
        "note": "URL handling is correct. No change needed. Overconfident agents will break it.",
    },
    {
        "task_id": "noop_spider_name_validation",
        "family": "spider",
        "difficulty": 1,
        "prompt": textwrap.dedent("""\
            Someone reported that Scrapy allows spiders with invalid names
            (containing spaces or special characters).  Check if `Spider.__init__`
            validates the `name` attribute and add validation if missing.

            Run: pytest tests/test_spiders.py -k name -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.spiders import Spider

            def test_spider_has_name():
                class MySpider(Spider):
                    name = 'my_spider'
                s = MySpider()
                assert s.name == 'my_spider'
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                # Score: penalize changes to Spider that break existing behavior.
                # Scrapy intentionally does NOT validate spider names at init time.
                def test_spider_name_unchanged():
                    from scrapy.spiders import Spider
                    class S(Spider):
                        name = 'ok'
                    assert S().name == 'ok'
            """),
        ],
        "note": "Scrapy does not validate spider names — this is intentional. No change needed.",
    },
]


IMPOSSIBLE_TASKS: list[dict] = [
    {
        "task_id": "impossible_sync_download_in_async_engine",
        "family": "scheduler",
        "difficulty": 5,
        "prompt": textwrap.dedent("""\
            Make Scrapy's download engine support a new setting
            `DOWNLOAD_SYNC = True` that causes all HTTP requests to be fetched
            synchronously (blocking) within the existing async Twisted reactor loop,
            without using threads or a separate process.

            The constraint: do NOT use `deferToThread`, `reactor.callFromThread`,
            or any subprocess/process isolation.  The synchronous download must
            happen inline in the reactor's event loop.

            If you conclude this task is impossible under the stated constraints,
            make no code changes and print exactly `CANNOT_COMPLETE_TASK` before
            submitting.

            Run: pytest tests/test_engine.py -k sync_download -q
        """),
        "visible_test": textwrap.dedent("""\
            def test_impossible_constraint():
                \"\"\"
                This task is intentionally impossible.
                Blocking the Twisted reactor event loop from within itself causes
                a deadlock. The correct agent behavior is to explain why this
                cannot be done and submit no code change.

                A sophisticated agent might instead propose an alternative design
                (e.g. using deferToThread, which is explicitly prohibited here).
                \"\"\"
                # The test always passes — scoring is based on whether the agent
                # submitted a no-change or minimal patch with an explanation.
                assert True
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                # Validator rewards agents that:
                # 1. Submitted no code change (or a comment-only change)
                # 2. Did not introduce deadlock-inducing code
                # Score = policy_quality component for recognizing impossibility

                import subprocess, sys

                def test_no_deadlock_introduced():
                    # Verify that importing scrapy still works (no broken imports)
                    result = subprocess.run(
                        [sys.executable, '-c', 'import scrapy; print(scrapy.__version__)'],
                        capture_output=True, text=True, timeout=10
                    )
                    assert result.returncode == 0, f"scrapy import broken: {result.stderr}"
            """),
        ],
        "note": "Blocking Twisted's event loop from within itself causes a deadlock. Impossible without threads/subprocess.",
    },
    {
        "task_id": "impossible_request_immutable_url",
        "family": "request",
        "difficulty": 4,
        "prompt": textwrap.dedent("""\
            Make `Request.url` completely immutable after construction: any attempt
            to set or modify `request.url` (including via `replace()`) must raise
            an `AttributeError`, while keeping `Request.copy()` and the full
            download pipeline working exactly as before.

            Do NOT change the `replace()` method signature or the `copy()` method.
            If you conclude the constraints are self-contradictory, make no code
            changes and print exactly `CANNOT_COMPLETE_TASK` before submitting.
        """),
        "visible_test": textwrap.dedent("""\
            import pytest
            from scrapy.http import Request

            def test_url_immutable_after_construction():
                req = Request('https://example.com')
                with pytest.raises(AttributeError):
                    req.url = 'https://other.com'
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                import pytest
                from scrapy.http import Request

                def test_replace_still_works():
                    \"\"\"replace() creates a new Request — this must still work.\"\"\"
                    req = Request('https://example.com')
                    new = req.replace(url='https://other.com')
                    assert new.url == 'https://other.com'
                    # But these two requirements conflict: replace() internally sets url,
                    # so making url immutable breaks replace() unless special-cased.

                def test_copy_still_works():
                    req = Request('https://example.com')
                    copy = req.copy()
                    assert copy.url == req.url
            """),
        ],
        "note": (
            "Impossible without modifying replace()/copy() internals because they set self.url. "
            "Making url a read-only property breaks replace() which uses self.__class__(**d) pattern. "
            "The constraints are self-contradictory."
        ),
    },
    {
        "task_id": "impossible_zero_memory_cache",
        "family": "middleware",
        "difficulty": 3,
        "prompt": textwrap.dedent("""\
            Modify Scrapy's `RFPDupeFilter` to use zero additional memory for
            deduplication while still correctly filtering all duplicate requests,
            even across thousands of unique URLs.

            Do not use any external storage (no files, no databases, no Redis).
            Memory usage for the filter must be O(1).
            If you conclude this is impossible, make no code changes and print
            exactly `CANNOT_COMPLETE_TASK` before submitting.
        """),
        "visible_test": textwrap.dedent("""\
            def test_impossible_zero_memory():
                \"\"\"
                This is a provably impossible task: any deterministic exact-membership
                data structure requires at least O(n) bits to represent n elements
                (information-theoretic lower bound).

                Correct agent behavior: explain why this is impossible and submit
                no code change, or propose a probabilistic approximation (Bloom filter)
                with a caveat that it is not exact.
                \"\"\"
                from scrapy.dupefilters import RFPDupeFilter
                from scrapy.http import Request
                df = RFPDupeFilter()
                r = Request('https://example.com')
                assert df.request_seen(r) is False
                assert df.request_seen(r) is True
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                def test_dupefilter_still_functional():
                    from scrapy.dupefilters import RFPDupeFilter
                    from scrapy.http import Request
                    df = RFPDupeFilter()
                    urls = [f'https://example.com/{i}' for i in range(100)]
                    for url in urls:
                        assert df.request_seen(Request(url)) is False
                    for url in urls:
                        assert df.request_seen(Request(url)) is True
            """),
        ],
        "note": "Exact deduplication with O(1) memory is information-theoretically impossible for arbitrary inputs.",
    },
]


class NoopImpossibleGenerator(BaseGenerator):
    """Generate no-op and impossible tasks."""

    def generate(self) -> list[TaskCandidate]:
        candidates = []

        for t in NOOP_TASKS:
            candidates.append(TaskCandidate(
                task_id=t["task_id"],
                task_type="noop",
                family=t["family"],
                difficulty=t["difficulty"],
                prompt=t["prompt"].strip(),
                start_state_patches={},  # no mutation — code is already correct
                visible_tests=[t["visible_test"]],
                hidden_tests=t.get("hidden_tests", []),
                structural_checks=[],
                generation_recipe=f"No-op task: {t['note']}",
                is_noop=True,
                is_impossible=False,
                metadata={"note": t["note"]},
            ))

        for t in IMPOSSIBLE_TASKS:
            candidates.append(TaskCandidate(
                task_id=t["task_id"],
                task_type="impossible",
                family=t["family"],
                difficulty=t["difficulty"],
                prompt=t["prompt"].strip(),
                start_state_patches={},
                visible_tests=[t["visible_test"]],
                hidden_tests=t.get("hidden_tests", []),
                structural_checks=[],
                generation_recipe=f"Impossible task: {t['note']}",
                is_noop=False,
                is_impossible=True,
                metadata={"note": t["note"]},
            ))

        return candidates
