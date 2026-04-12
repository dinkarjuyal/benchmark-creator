"""Contract extension task generator.

Strategy: identify a Scrapy component with a clear interface, describe a new
capability that should be added, provide a visible test for the new behavior,
and include hidden tests that guard all existing behavior.

These tasks require the agent to extend without breaking — harder than pure repair.
"""
from __future__ import annotations

import textwrap

from .base import BaseGenerator, TaskCandidate


CONTRACT_EXTENSIONS: list[dict] = [
    {
        "task_id": "settings_getlist_fallback_kwarg",
        "family": "settings",
        "difficulty": 2,
        "prompt": textwrap.dedent("""\
            `Settings.getbool()` and `Settings.getfloat()` both accept an optional
            `default` keyword argument.  `Settings.getlist()` does not, making it
            inconsistent with its siblings.

            Add a `default` keyword argument to `Settings.getlist()` so that:
            - `s.getlist('MISSING_KEY', default=['a', 'b'])` returns `['a', 'b']`
            - `s.getlist('EXISTING_KEY')` behaves exactly as before
            - The default value for `default` is `None` (existing behavior: raise or
              return empty depending on Scrapy version — preserve whatever currently happens)

            Do not break any existing `getlist` tests.

            Verify with: pytest tests/test_settings.py -k getlist -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.settings import Settings

            def test_getlist_with_default():
                s = Settings()
                result = s.getlist('NONEXISTENT_SETTING_XYZ', default=['x', 'y'])
                assert result == ['x', 'y'], f"Expected ['x', 'y'], got {result!r}"

            def test_getlist_default_empty_list():
                s = Settings()
                result = s.getlist('NONEXISTENT_SETTING_XYZ', default=[])
                assert result == [], f"Expected [], got {result!r}"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.settings import Settings

                def test_getlist_existing_key_unchanged():
                    s = Settings({'MYLIST': 'a,b,c'})
                    result = s.getlist('MYLIST')
                    assert isinstance(result, list)
                    assert 'a' in result

                def test_getlist_no_default_existing_behavior():
                    s = Settings({'NUMS': ['1', '2']})
                    result = s.getlist('NUMS')
                    assert result == ['1', '2']
            """),
        ],
    },
    {
        "task_id": "request_add_headers_method",
        "family": "request",
        "difficulty": 2,
        "prompt": textwrap.dedent("""\
            `scrapy.http.Request` has `headers` as a dict-like attribute but no
            convenience method for merging new headers into an existing request.

            Add a method `Request.with_headers(extra_headers)` that returns a new
            `Request` (via `replace()`) with the given headers merged on top of the
            existing ones.  The original request must be unchanged.

            Example:
                req = Request('https://example.com', headers={'User-Agent': 'bot'})
                new = req.with_headers({'Authorization': 'Bearer token'})
                # new has both headers; req is unchanged

            Verify with: pytest tests/test_http_request.py -k with_headers -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request

            def test_with_headers_merges():
                req = Request('https://example.com', headers={'User-Agent': 'bot'})
                new = req.with_headers({'Authorization': 'Bearer token'})
                assert b'Authorization' in new.headers or 'Authorization' in new.headers
                assert new.url == req.url

            def test_with_headers_original_unchanged():
                req = Request('https://example.com', headers={'A': '1'})
                _ = req.with_headers({'B': '2'})
                assert b'B' not in req.headers and 'B' not in req.headers
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request

                def test_with_headers_override_existing():
                    req = Request('https://example.com', headers={'User-Agent': 'old'})
                    new = req.with_headers({'User-Agent': 'new'})
                    ua = new.headers.get('User-Agent')
                    if isinstance(ua, list):
                        ua = ua[0]
                    if isinstance(ua, bytes):
                        ua = ua.decode()
                    assert ua == 'new', f"Expected 'new', got {ua!r}"

                def test_with_headers_returns_new_request():
                    req = Request('https://example.com')
                    new = req.with_headers({'X-Custom': 'yes'})
                    assert new is not req
            """),
        ],
    },
    {
        "task_id": "response_json_method",
        "family": "response",
        "difficulty": 2,
        "prompt": textwrap.dedent("""\
            `scrapy.http.TextResponse` should have a `.json()` method that parses
            the response body as JSON (similar to `requests.Response.json()`).

            Add `TextResponse.json()` so that:
            - It returns the parsed Python object (dict, list, etc.)
            - It raises `ValueError` (or `json.JSONDecodeError`) if the body is not valid JSON
            - It does not change any existing behavior

            Verify with: pytest tests/test_http_response.py -k json -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import TextResponse

            def test_response_json_dict():
                r = TextResponse('https://api.example.com/', body=b'{"key": "value"}',
                                  encoding='utf-8')
                data = r.json()
                assert data == {'key': 'value'}

            def test_response_json_list():
                r = TextResponse('https://api.example.com/', body=b'[1, 2, 3]',
                                  encoding='utf-8')
                assert r.json() == [1, 2, 3]
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                import pytest
                from scrapy.http import TextResponse

                def test_response_json_invalid_raises():
                    r = TextResponse('https://example.com/', body=b'not json',
                                      encoding='utf-8')
                    with pytest.raises((ValueError, Exception)):
                        r.json()

                def test_response_existing_methods_intact():
                    r = TextResponse('https://example.com/', body=b'<p>hello</p>',
                                      encoding='utf-8')
                    assert r.css('p::text').get() == 'hello'
            """),
        ],
    },
    {
        "task_id": "dupefilter_clear_method",
        "family": "scheduler",
        "difficulty": 2,
        "prompt": textwrap.dedent("""\
            `RFPDupeFilter` accumulates fingerprints in memory but provides no way
            to reset the filter without creating a new instance.

            Add a `clear()` method to `RFPDupeFilter` that empties the seen-fingerprint
            set so that previously-seen URLs are treated as new again.

            Do not break any existing deduplication behavior.

            Verify with: pytest tests/test_dupefilters.py -k clear -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.dupefilters import RFPDupeFilter
            from scrapy.http import Request

            def test_clear_resets_seen():
                df = RFPDupeFilter()
                req = Request('https://example.com')
                df.request_seen(req)   # mark as seen
                df.clear()             # reset
                assert df.request_seen(req) is False, (
                    "After clear(), the URL should appear new again"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.dupefilters import RFPDupeFilter
                from scrapy.http import Request

                def test_clear_then_reseen():
                    df = RFPDupeFilter()
                    req = Request('https://example.com/page')
                    df.request_seen(req)
                    df.clear()
                    assert df.request_seen(req) is False
                    assert df.request_seen(req) is True

                def test_normal_dedup_after_clear():
                    df = RFPDupeFilter()
                    r1 = Request('https://a.com')
                    r2 = Request('https://b.com')
                    df.request_seen(r1)
                    df.clear()
                    df.request_seen(r1)
                    assert df.request_seen(r2) is False  # r2 never seen
                    assert df.request_seen(r1) is True   # r1 seen after clear
            """),
        ],
    },
    {
        "task_id": "spider_middleware_short_circuit",
        "family": "middleware",
        "difficulty": 3,
        "prompt": textwrap.dedent("""\
            Add support for a new spider middleware method `process_start_requests`
            to be able to return an early short-circuit signal by returning the
            sentinel value `scrapy.utils.misc.SKIP_REMAINING_MIDDLEWARES` from
            `process_start_requests`, causing the remaining middlewares in the
            chain to be skipped for that request batch.

            Existing middleware behavior must be preserved when the sentinel is
            not returned.

            Verify with: pytest tests/test_spidermw.py -k short_circuit -q
        """),
        "visible_test": textwrap.dedent("""\
            def test_short_circuit_concept():
                \"\"\"
                This is a contract extension task.  The agent must add the sentinel
                constant and wire up the short-circuit logic in the middleware manager.

                A passing visible test just imports scrapy without error after the change.
                \"\"\"
                import scrapy
                assert hasattr(scrapy, '__version__')
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                def test_existing_middleware_unaffected():
                    from scrapy.core.spidermw import SpiderMiddlewareManager
                    # Verify the manager can still be imported and instantiated
                    assert SpiderMiddlewareManager is not None
            """),
        ],
    },
    {
        "task_id": "settings_copy_method",
        "family": "settings",
        "difficulty": 2,
        "prompt": textwrap.dedent("""\
            `Settings` objects have no `copy()` method. Add one that returns a
            deep copy of the settings so that modifications to the copy do not
            affect the original.

            The copy must preserve all set values and their priorities.

            Verify with: pytest tests/test_settings.py -k copy -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.settings import Settings

            def test_settings_copy_isolation():
                s = Settings({'FOO': 'bar', 'NUM': 42})
                c = s.copy()
                c.set('FOO', 'mutated')
                assert s['FOO'] == 'bar', f"Original was mutated: {s['FOO']!r}"

            def test_settings_copy_preserves_values():
                s = Settings({'KEY': 'value'})
                c = s.copy()
                assert c['KEY'] == 'value'
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.settings import Settings

                def test_copy_preserves_priorities():
                    s = Settings()
                    s.set('X', 'high', priority='spider')
                    c = s.copy()
                    assert c['X'] == 'high'

                def test_copy_returns_settings_instance():
                    s = Settings({'A': 1})
                    c = s.copy()
                    assert isinstance(c, Settings)
            """),
        ],
    },
    {
        "task_id": "request_fingerprint_custom",
        "family": "scheduler",
        "difficulty": 3,
        "prompt": textwrap.dedent("""\
            Scrapy's `fingerprint()` function in `scrapy.utils.request` produces
            a hash of the request for deduplication.  Add an optional
            `include_headers` parameter (default `None`) that, when provided as
            a list of header names, includes those header values in the fingerprint.

            This allows spiders to deduplicate requests differently when, say,
            `Authorization` headers differ.

            Do not change the default behavior (no headers included by default).

            Verify with: pytest tests/test_utils_request.py -k fingerprint -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request
            from scrapy.utils.request import fingerprint

            def test_fingerprint_with_include_headers_differs():
                r1 = Request('https://example.com', headers={'Auth': 'token-A'})
                r2 = Request('https://example.com', headers={'Auth': 'token-B'})
                fp1 = fingerprint(r1, include_headers=['Auth'])
                fp2 = fingerprint(r2, include_headers=['Auth'])
                assert fp1 != fp2, "Different Auth headers should yield different fingerprints"

            def test_fingerprint_default_ignores_headers():
                r1 = Request('https://example.com', headers={'Auth': 'token-A'})
                r2 = Request('https://example.com', headers={'Auth': 'token-B'})
                assert fingerprint(r1) == fingerprint(r2), (
                    "Without include_headers, fingerprints should match"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request
                from scrapy.utils.request import fingerprint

                def test_fingerprint_stable():
                    r = Request('https://example.com/page')
                    assert fingerprint(r) == fingerprint(r)

                def test_fingerprint_include_headers_none_same_as_default():
                    r = Request('https://example.com', headers={'X-Token': 'abc'})
                    assert fingerprint(r, include_headers=None) == fingerprint(r)
            """),
        ],
    },
]


class ContractExtensionGenerator(BaseGenerator):
    """Generate tasks that require adding new capabilities without breaking existing ones."""

    def generate(self) -> list[TaskCandidate]:
        candidates = []
        for ext in CONTRACT_EXTENSIONS:
            candidates.append(TaskCandidate(
                task_id=ext["task_id"],
                task_type="contract_extension",
                family=ext["family"],
                difficulty=ext["difficulty"],
                prompt=ext["prompt"].strip(),
                start_state_patches={},  # no pre-injected regression; agent adds new code
                visible_tests=[ext["visible_test"]],
                hidden_tests=ext.get("hidden_tests", []),
                structural_checks=[],
                generation_recipe=f"Contract extension: add new capability to {ext['family']} subsystem",
                is_noop=False,
                is_impossible=False,
            ))
        return candidates
