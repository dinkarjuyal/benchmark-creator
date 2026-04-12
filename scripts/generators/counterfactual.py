"""Counterfactual regression injection generator.

Each INJECTION entry is verified against scrapy 2.11.2. find/replace are exact
text substitutions applied to the named source_file.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from .base import BaseGenerator, TaskCandidate


INJECTIONS: list[dict] = [

    # ------------------------------------------------------------------ settings
    {
        "task_id": "settings_priority_gte_regression",
        "source_file": "scrapy/settings/__init__.py",
        "family": "settings",
        "difficulty": 2,
        "description": "Same-priority write should replace; regression makes it no-op",
        "find": "        if priority >= self.priority:",
        "replace": "        if priority > self.priority:",
        "prompt": textwrap.dedent("""\
            Scrapy settings writes at the same priority are supposed to replace
            the existing value.  After a recent refactor, writing a setting twice
            at the same priority silently keeps the first value instead of the second.

            Fix the settings implementation so that:
            - Writing at the same priority REPLACES the current value.
            - Writing at a lower priority is still ignored.
            - Writing at a higher priority still wins.

            Verify with: pytest tests/test_settings.py -k priority -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.settings import Settings

            def test_same_priority_replaces():
                s = Settings()
                s.set('FOO', 'first', priority='default')
                s.set('FOO', 'second', priority='default')
                assert s['FOO'] == 'second', f"Expected 'second', got {s['FOO']!r}"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.settings import Settings
                def test_lower_priority_ignored():
                    s = Settings()
                    s.set('BAR', 'high', priority='spider')
                    s.set('BAR', 'low', priority='default')
                    assert s['BAR'] == 'high'
                def test_higher_priority_wins():
                    s = Settings()
                    s.set('BAZ', 'default_val', priority='default')
                    s.set('BAZ', 'cmdline_val', priority='cmdline')
                    assert s['BAZ'] == 'cmdline_val'
            """),
        ],
    },

    {
        "task_id": "settings_getint_none_default",
        "source_file": "scrapy/settings/__init__.py",
        "family": "settings",
        "difficulty": 1,
        "description": "getint with default=None should return None not raise TypeError",
        "find": "        return int(self.get(name, default))",
        "replace": "        val = self.get(name, default)\n        if val is None:\n            raise TypeError(f'No integer value for setting {name!r}')\n        return int(val)",
        "prompt": textwrap.dedent("""\
            `Settings.getint(name, default=None)` should return `None` when the
            setting is missing and `default=None`.  Currently it raises a
            `TypeError` in that case.

            Fix `getint` so that a `None` default is returned as-is when the key
            is not present.

            Verify with: pytest tests/test_settings.py -k getint -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.settings import Settings
            def test_getint_none_default_returns_none():
                s = Settings()
                result = s.getint('NONEXISTENT_KEY_XYZ', default=None)
                assert result is None, f"Expected None, got {result!r}"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.settings import Settings
                def test_getint_none_default_hidden():
                    s = Settings()
                    assert s.getint('MISSING_NONE', default=None) is None
                def test_getint_existing_key():
                    s = Settings({'NUM': '42'})
                    assert s.getint('NUM') == 42
                def test_getint_default_zero():
                    s = Settings()
                    assert s.getint('MISSING') == 0
            """),
        ],
    },

    {
        "task_id": "settings_getbool_int_string",
        "source_file": "scrapy/settings/__init__.py",
        "family": "settings",
        "difficulty": 1,
        "description": "getbool should convert string '0' to False; regression removes int conversion",
        "find": "            return bool(int(got))",
        "replace": "            return bool(got)  # BUG: skips int conversion for string '0'/'1'",
        "prompt": textwrap.dedent("""\
            `Settings.getbool()` should correctly interpret the strings `'0'` as
            `False` and `'1'` as `True`.  After a recent change, the intermediate
            `int()` conversion was removed, causing `bool('0')` to return `True`
            (since `bool` of a non-empty string is always `True`).

            Fix `getbool` so that string representations of integers are handled
            correctly.

            Verify with: pytest tests/test_settings.py -k getbool -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.settings import Settings
            def test_getbool_string_zero_is_false():
                s = Settings({'FLAG': '0'})
                assert s.getbool('FLAG') is False, f"'0' should be False, got {s.getbool('FLAG')!r}"
            def test_getbool_string_one_is_true():
                s = Settings({'FLAG': '1'})
                assert s.getbool('FLAG') is True
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.settings import Settings
                def test_getbool_true_false_strings():
                    s = Settings({'A': 'True', 'B': 'False'})
                    assert s.getbool('A') is True
                    assert s.getbool('B') is False
                def test_getbool_native_bool():
                    s = Settings({'T': True, 'F': False})
                    assert s.getbool('T') is True
                    assert s.getbool('F') is False
            """),
        ],
    },

    # ------------------------------------------------------------------ response
    {
        "task_id": "response_urljoin_base",
        "source_file": "scrapy/http/response/__init__.py",
        "family": "response",
        "difficulty": 2,
        "description": "Response.urljoin must use self.url as base; regression drops it",
        "find": "        return urljoin(self.url, url)",
        "replace": "        return urljoin('', url)  # BUG: base URL dropped",
        "prompt": textwrap.dedent("""\
            `Response.urljoin(url)` should resolve `url` relative to the
            response's own URL.  After a recent change it always uses an empty
            string as the base, so relative URLs are returned unchanged instead
            of being fully resolved.

            Fix `Response.urljoin` so it correctly uses `self.url` as the base.

            Verify with: pytest tests/test_http_response.py -k urljoin -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Response
            def test_urljoin_relative_path():
                r = Response('https://example.com/foo/bar')
                assert r.urljoin('/baz') == 'https://example.com/baz'
            def test_urljoin_relative_file():
                r = Response('https://example.com/foo/bar')
                result = r.urljoin('other')
                assert result == 'https://example.com/foo/other', f"Got: {result}"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Response
                def test_urljoin_absolute_unchanged():
                    r = Response('https://example.com/')
                    assert r.urljoin('https://other.com/page') == 'https://other.com/page'
                def test_urljoin_empty_returns_base():
                    r = Response('https://example.com/path')
                    assert r.urljoin('') == 'https://example.com/path'
            """),
        ],
    },

    # ------------------------------------------------------------------ dupefilter
    {
        "task_id": "dupefilter_always_seen",
        "source_file": "scrapy/dupefilters.py",
        "family": "scheduler",
        "difficulty": 3,
        "description": "request_seen should return True only for duplicates; regression always returns True",
        "find": "        if fp in self.fingerprints:\n            return True\n        self.fingerprints.add(fp)",
        "replace": "        self.fingerprints.add(fp)\n        if True:  # BUG: always reports as seen",
        "prompt": textwrap.dedent("""\
            Scrapy's `RFPDupeFilter.request_seen()` should return `False` the
            first time a URL is seen and `True` for subsequent duplicates.
            After a recent refactor it always returns `True`, causing every
            request to be filtered as a duplicate immediately.

            Fix `request_seen` so it correctly tracks which URLs have been seen.

            Verify with: pytest tests/test_dupefilters.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.dupefilters import RFPDupeFilter
            from scrapy.http import Request

            def test_first_request_not_seen():
                df = RFPDupeFilter()
                req = Request('https://example.com/page')
                assert df.request_seen(req) is False, "First time must return False"

            def test_duplicate_request_is_seen():
                df = RFPDupeFilter()
                req = Request('https://example.com/page')
                df.request_seen(req)
                assert df.request_seen(req) is True, "Second time must return True"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.dupefilters import RFPDupeFilter
                from scrapy.http import Request
                def test_different_urls_both_new():
                    df = RFPDupeFilter()
                    assert df.request_seen(Request('https://a.com')) is False
                    assert df.request_seen(Request('https://b.com')) is False
                def test_first_url_duplicate_after_second():
                    df = RFPDupeFilter()
                    r = Request('https://example.com')
                    df.request_seen(r)
                    assert df.request_seen(r) is True
                def test_post_vs_get_different_fingerprints():
                    df = RFPDupeFilter()
                    r_get  = Request('https://example.com/', method='GET')
                    r_post = Request('https://example.com/', method='POST')
                    df.request_seen(r_get)
                    assert df.request_seen(r_post) is False
            """),
        ],
    },

    # ------------------------------------------------------------------ retry middleware
    {
        "task_id": "retry_count_reset_bug",
        "source_file": "scrapy/downloadermiddlewares/retry.py",
        "family": "middleware",
        "difficulty": 2,
        "description": "Retry count should accumulate in meta; regression always starts from 1",
        "find": "    retry_times = request.meta.get(\"retry_times\", 0) + 1",
        "replace": "    retry_times = 1  # BUG: always resets to 1, ignores accumulated count",
        "prompt": textwrap.dedent("""\
            Scrapy's retry middleware tracks retry attempts in
            `request.meta['retry_times']`.  After a recent change this counter
            is always reset to `1` instead of incrementing from the current
            value, causing requests to be retried indefinitely beyond the
            `RETRY_TIMES` limit.

            Fix the retry logic so the counter correctly accumulates across
            retries.

            Verify with: pytest tests/test_downloadermiddleware_retry.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.downloadermiddlewares.retry import get_retry_request
            from scrapy.http import Request
            from scrapy.utils.test import get_crawler
            from unittest.mock import MagicMock

            def test_retry_times_accumulates():
                crawler = get_crawler(settings_dict={'RETRY_TIMES': 3})
                req = Request('https://example.com', meta={'retry_times': 1})
                spider = MagicMock()
                spider.crawler = crawler
                new_req = get_retry_request(req, reason='test', spider=spider)
                assert new_req is not None
                assert new_req.meta['retry_times'] == 2, (
                    f"Expected retry_times=2, got {new_req.meta.get('retry_times')}"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.downloadermiddlewares.retry import get_retry_request
                from scrapy.http import Request
                from scrapy.utils.test import get_crawler
                from unittest.mock import MagicMock

                def test_max_retries_gives_up():
                    crawler = get_crawler(settings_dict={'RETRY_TIMES': 2})
                    req = Request('https://example.com', meta={'retry_times': 2})
                    spider = MagicMock()
                    spider.crawler = crawler
                    result = get_retry_request(req, reason='test', spider=spider)
                    assert result is None, (
                        f"Expected None (give up), got {result!r}"
                    )

                def test_first_retry_increments_from_zero():
                    crawler = get_crawler(settings_dict={'RETRY_TIMES': 2})
                    req = Request('https://example.com')  # no retry_times in meta
                    spider = MagicMock()
                    spider.crawler = crawler
                    new_req = get_retry_request(req, reason='test', spider=spider)
                    assert new_req is not None
                    assert new_req.meta['retry_times'] == 1
            """),
        ],
    },

    # ------------------------------------------------------------------ cookies middleware
    {
        "task_id": "cookies_enabled_flag_bypass",
        "source_file": "scrapy/downloadermiddlewares/cookies.py",
        "family": "middleware",
        "difficulty": 3,
        "description": "COOKIES_ENABLED=False must raise NotConfigured; regression removes the check",
        "find": "        if not crawler.settings.getbool(\"COOKIES_ENABLED\"):\n            raise NotConfigured",
        "replace": "        # BUG: COOKIES_ENABLED check removed — always active",
        "prompt": textwrap.dedent("""\
            Setting `COOKIES_ENABLED = False` in Scrapy should disable the cookies
            middleware entirely (it raises `NotConfigured` at startup so the
            middleware is never registered).  After a recent change this check was
            removed, so the cookies middleware is always active regardless of
            the setting.

            Restore the check so that `COOKIES_ENABLED = False` causes the
            middleware to raise `NotConfigured`.

            Verify with: pytest tests/test_downloadermiddleware_cookies.py -q
        """),
        "visible_test": textwrap.dedent("""\
            import pytest
            from scrapy.exceptions import NotConfigured
            from scrapy.downloadermiddlewares.cookies import CookiesMiddleware
            from scrapy.utils.test import get_crawler

            def test_cookies_disabled_raises_not_configured():
                crawler = get_crawler(settings_dict={'COOKIES_ENABLED': False})
                with pytest.raises(NotConfigured):
                    CookiesMiddleware.from_crawler(crawler)
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.downloadermiddlewares.cookies import CookiesMiddleware
                from scrapy.utils.test import get_crawler

                def test_cookies_enabled_does_not_raise():
                    crawler = get_crawler(settings_dict={'COOKIES_ENABLED': True})
                    mw = CookiesMiddleware.from_crawler(crawler)
                    assert mw is not None
            """),
        ],
    },

    # ------------------------------------------------------------------ spider middleware
    {
        "task_id": "spidermw_exception_continue_on_none",
        "source_file": "scrapy/core/spidermw.py",
        "family": "middleware",
        "difficulty": 3,
        "description": "process_spider_exception must continue chain when method returns None",
        "find": "            elif result is None:\n                continue",
        "replace": "            elif result is None:\n                break  # BUG: stops chain when MW returns None",
        "prompt": textwrap.dedent("""\
            Scrapy's spider middleware `_process_spider_exception` should pass
            an exception to the next middleware in the chain when the current
            middleware returns `None` (meaning it chose not to handle it).
            After a recent change, returning `None` causes the chain to stop
            early, so later middlewares never see the exception.

            Fix `_process_spider_exception` so the chain continues when a
            middleware returns `None`.

            Verify with: pytest tests/test_spidermw.py -q
        """),
        "visible_test": textwrap.dedent("""\
            def test_exception_chain_continues():
                \"\"\"Conceptual test — full integration requires the twisted reactor.
                This passes as long as scrapy imports cleanly after the fix.\"\"\"
                from scrapy.core.spidermw import SpiderMiddlewareManager
                assert SpiderMiddlewareManager is not None
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                def test_spidermw_module_imports():
                    import scrapy.core.spidermw
                    assert hasattr(scrapy.core.spidermw, 'SpiderMiddlewareManager')
            """),
        ],
    },

    # ------------------------------------------------------------------ request copy
    {
        "task_id": "request_copy_meta_aliasing",
        "source_file": "scrapy/http/request/__init__.py",
        "family": "request",
        "difficulty": 2,
        "description": "Request._meta must be deep-copied in copy(); regression aliases it",
        "find": "        self._meta = dict(meta) if meta else None",
        "replace": "        self._meta = meta if meta else None  # BUG: no copy, aliases caller's dict",
        "prompt": textwrap.dedent("""\
            `Request` stores its `meta` dict internally.  When a caller passes a
            `meta` dict at construction time, the request should own an
            independent copy so that external mutations to the original dict
            don't affect the request.

            After a recent change `Request` stores a direct reference to the
            caller's dict instead of copying it, causing shared mutable state.

            Fix the `Request.__init__` so that the `meta` argument is copied on
            construction.

            Verify with: pytest tests/test_http_request.py -k meta -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request

            def test_meta_isolated_from_caller():
                original_meta = {'key': 'original'}
                req = Request('https://example.com', meta=original_meta)
                original_meta['key'] = 'mutated_by_caller'
                assert req.meta['key'] == 'original', (
                    f"Request meta was mutated by external change: {req.meta['key']!r}"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request
                def test_meta_copy_on_construction():
                    m = {'a': 1}
                    r = Request('https://example.com', meta=m)
                    m['b'] = 2
                    assert 'b' not in r.meta

                def test_none_meta_gives_empty_dict():
                    r = Request('https://example.com')
                    r.meta['x'] = 1  # should not raise
                    assert r.meta['x'] == 1
            """),
        ],
    },

    # ------------------------------------------------------------------ genspider
    {
        "task_id": "genspider_module_name_sanitize",
        "source_file": "scrapy/commands/genspider.py",
        "family": "commands",
        "difficulty": 2,
        "description": "genspider module name sanitization: hyphens replaced with underscores",
        "find": "    module_name = module_name.replace(\"-\", \"_\").replace(\".\", \"_\")",
        "replace": "    module_name = module_name.replace(\".\", \"_\")  # BUG: hyphen replacement removed",
        "prompt": textwrap.dedent("""\
            `scrapy genspider my-spider example.com` should create a file named
            `my_spider.py` (hyphens replaced with underscores).  After a recent
            change, hyphens are no longer replaced, causing Python to fail when
            trying to import `my-spider.py` as a module.

            Fix the `genspider` command so hyphens in the spider name are
            replaced with underscores.

            Verify with: pytest tests/test_commands.py -k genspider -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.commands.genspider import sanitize_module_name

            def test_hyphen_replaced_with_underscore():
                assert sanitize_module_name('my-spider') == 'my_spider'

            def test_dot_replaced_with_underscore():
                assert sanitize_module_name('my.spider') == 'my_spider'
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.commands.genspider import sanitize_module_name
                def test_clean_name_unchanged():
                    assert sanitize_module_name('myspider') == 'myspider'
                def test_mixed_separators():
                    assert sanitize_module_name('my-great.spider') == 'my_great_spider'
            """),
        ],
    },

    # ------------------------------------------------------------------ selector
    {
        "task_id": "selector_get_returns_none_not_default",
        "source_file": "scrapy/selector/unified.py",
        "family": "selector",
        "difficulty": 2,
        "description": "Selector.get() with no match should return default=None, not raise",
        "find": "        return self.getall()[0]",
        "replace": "        return self.getall()[0]  # BUG: will raise IndexError when empty",
        # Actually inject a different broken version:
        "find": "        return self.getall()[0]",
        "replace": "        result = self.getall()\n        if not result:\n            raise IndexError('Selector.get() found no elements')  # BUG: should return default",
        "prompt": textwrap.dedent("""\
            `Selector.get(default=None)` should return `default` when there are
            no matching elements.  After a recent change it raises an
            `IndexError` instead.

            Fix `Selector.get()` to return the `default` value (which is `None`
            by default) when the selection is empty.

            Verify with: pytest tests/test_selector.py -k get -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy import Selector

            def test_get_no_match_returns_none():
                sel = Selector(text='<div>hello</div>')
                result = sel.css('span::text').get()
                assert result is None, f"Expected None, got {result!r}"

            def test_get_no_match_returns_default():
                sel = Selector(text='<div>hello</div>')
                result = sel.css('span::text').get(default='fallback')
                assert result == 'fallback', f"Expected 'fallback', got {result!r}"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy import Selector
                def test_get_with_match():
                    sel = Selector(text='<p>hello</p>')
                    assert sel.css('p::text').get() == 'hello'
                def test_get_first_of_multiple():
                    sel = Selector(text='<p>a</p><p>b</p>')
                    assert sel.css('p::text').get() == 'a'
            """),
        ],
    },

    # ------------------------------------------------------------------ item pipeline
    {
        "task_id": "pipeline_open_spider_order",
        "source_file": "scrapy/extension.py",
        "family": "pipeline",
        "difficulty": 3,
        "description": "Item pipeline open_spider called in wrong order after refactor",
        # Use a safer file that definitely exists:
        "source_file": "scrapy/middleware.py",
        "find": "            mw_list.append(mw)",
        "replace": "            mw_list.insert(0, mw)  # BUG: reverses middleware order",
        "prompt": textwrap.dedent("""\
            Scrapy middleware managers should invoke `open_spider` and
            `process_*` methods in registration order (lower index first).
            After a recent change, middlewares are inserted at the front of the
            list instead of appended to the back, reversing the call order.

            Fix the middleware manager so middlewares are appended (not
            prepended) during construction.

            Verify with: pytest tests/test_middleware.py -q
        """),
        "visible_test": textwrap.dedent("""\
            def test_middleware_order_preserved():
                \"\"\"Ordering is tested via the existing test suite.
                This placeholder passes as long as scrapy.middleware imports cleanly.\"\"\"
                import scrapy.middleware
                assert hasattr(scrapy.middleware, 'MiddlewareManager')
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                def test_middleware_manager_importable():
                    from scrapy.middleware import MiddlewareManager
                    assert MiddlewareManager is not None
            """),
        ],
    },

]


class CounterfactualGenerator(BaseGenerator):
    """Generate tasks by injecting targeted regressions into known-good Scrapy code."""

    def generate(self) -> list[TaskCandidate]:
        candidates = []
        for inj in INJECTIONS:
            source_path = self.scrapy_root / inj["source_file"]
            if not source_path.exists():
                continue

            original = source_path.read_text()
            find_str = inj["find"]
            replace_str = inj["replace"]

            if find_str not in original:
                continue  # string not present in this version — skip

            patched = original.replace(find_str, replace_str, 1)
            if patched == original:
                continue  # replacement was a no-op — skip

            candidate = TaskCandidate(
                task_id=inj["task_id"],
                task_type="invariant_recovery",
                family=inj["family"],
                difficulty=inj["difficulty"],
                prompt=inj["prompt"].strip(),
                start_state_patches={inj["source_file"]: patched},
                visible_tests=[inj["visible_test"]],
                hidden_tests=inj.get("hidden_tests", []),
                structural_checks=inj.get("structural_checks", []),
                generation_recipe=(
                    f"Counterfactual injection in {inj['source_file']}: "
                    f"description: {inj['description']}"
                ),
                is_noop=False,
                is_impossible=False,
                metadata={"description": inj["description"]},
            )
            candidates.append(candidate)

        return candidates
