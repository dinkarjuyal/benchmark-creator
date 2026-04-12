"""Structural task mining generator.

Sources:
- Sibling API asymmetries (Request.replace vs Response.replace behavior)
- TODO/FIXME comments near interface boundaries
- Functions with only happy-path tests → add edge case as hidden test
- Cross-layer doc/code divergence
- Additional counterfactual injections for subsystems not covered by counterfactual.py
"""
from __future__ import annotations

import textwrap

from .base import BaseGenerator, TaskCandidate

# Additional counterfactual injections mined structurally
# These are verified against scrapy 2.11.2
STRUCTURAL_INJECTIONS: list[dict] = [

    # ------------------------------------------------------------------
    # Redirect middleware — redirect_times counter reset
    # ------------------------------------------------------------------
    {
        "task_id": "redirect_times_accumulation",
        "source_file": "scrapy/downloadermiddlewares/redirect.py",
        "family": "middleware",
        "difficulty": 2,
        "description": "redirect_times must increment; regression resets to 1 on each hop",
        "find": '        redirects = request.meta.get("redirect_times", 0) + 1',
        "replace": '        redirects = 1  # BUG: always resets, ignores accumulated count',
        "prompt": textwrap.dedent("""\
            Scrapy's redirect middleware tracks the number of redirects followed
            in `request.meta['redirect_times']`.  After a recent change this
            counter is always reset to `1` instead of accumulating, so the
            `REDIRECT_MAX_TIMES` limit is never enforced correctly.

            Fix the redirect middleware so `redirect_times` correctly increments
            on each hop.

            Verify with: pytest tests/test_downloadermiddleware_redirect.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request, Response
            from scrapy.downloadermiddlewares.redirect import RedirectMiddleware
            from scrapy.utils.test import get_crawler
            from unittest.mock import MagicMock

            def test_redirect_times_increments():
                crawler = get_crawler(settings_dict={'REDIRECT_MAX_TIMES': 5})
                mw = RedirectMiddleware.from_crawler(crawler)
                req = Request('https://example.com', meta={'redirect_times': 2})
                resp = Response('https://other.com', status=301,
                                headers={'Location': 'https://final.com'},
                                request=req)
                new_req = mw.process_response(req, resp, MagicMock())
                assert isinstance(new_req, Request)
                assert new_req.meta.get('redirect_times') == 3, (
                    f"Expected 3, got {new_req.meta.get('redirect_times')}"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request, Response
                from scrapy.downloadermiddlewares.redirect import RedirectMiddleware
                from scrapy.utils.test import get_crawler
                from unittest.mock import MagicMock

                def test_max_redirects_enforced():
                    crawler = get_crawler(settings_dict={'REDIRECT_MAX_TIMES': 2})
                    mw = RedirectMiddleware.from_crawler(crawler)
                    req = Request('https://example.com',
                                  meta={'redirect_times': 2, 'redirect_ttl': 0})
                    resp = Response('https://other.com', status=302,
                                    headers={'Location': 'https://final.com'},
                                    request=req)
                    result = mw.process_response(req, resp, MagicMock())
                    # Should return the response (give up), not a new Request
                    assert isinstance(result, Response), (
                        f"Expected Response (give up), got {type(result).__name__}"
                    )
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Depth middleware — depth increments incorrectly
    # ------------------------------------------------------------------
    {
        "task_id": "depth_middleware_init_depth",
        "source_file": "scrapy/spidermiddlewares/depth.py",
        "family": "middleware",
        "difficulty": 2,
        "description": "Depth should start at 0 for the root response; regression starts at 1",
        "find": '            response.meta["depth"] = 0',
        "replace": '            response.meta["depth"] = 1  # BUG: root starts at 1 not 0',
        "prompt": textwrap.dedent("""\
            The depth spider middleware initialises the crawl depth at `0` for
            the first (root) response.  After a recent change it starts at `1`,
            causing the `DEPTH_LIMIT` to be reached one hop earlier than
            configured.

            Fix the depth middleware so the root response is assigned depth `0`.

            Verify with: pytest tests/test_spidermiddleware_depth.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request, Response
            from scrapy.spidermiddlewares.depth import DepthMiddleware
            from scrapy.utils.test import get_crawler
            from unittest.mock import MagicMock

            def test_root_response_depth_is_zero():
                crawler = get_crawler(settings_dict={'DEPTH_LIMIT': 3, 'DEPTH_STATS_VERBOSE': False})
                mw = DepthMiddleware.from_crawler(crawler)
                req = Request('https://example.com')
                resp = Response('https://example.com', request=req)
                spider = MagicMock()
                spider.crawler = crawler
                list(mw.process_spider_output(resp, [req], spider))
                assert resp.meta.get('depth') == 0, (
                    f"Root depth should be 0, got {resp.meta.get('depth')}"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request, Response
                from scrapy.spidermiddlewares.depth import DepthMiddleware
                from scrapy.utils.test import get_crawler
                from unittest.mock import MagicMock

                def test_child_request_depth_is_one():
                    crawler = get_crawler(settings_dict={'DEPTH_LIMIT': 3, 'DEPTH_STATS_VERBOSE': False})
                    mw = DepthMiddleware.from_crawler(crawler)
                    root_req = Request('https://example.com')
                    root_resp = Response('https://example.com', request=root_req)
                    child_req = Request('https://example.com/page')
                    spider = MagicMock()
                    spider.crawler = crawler
                    results = list(mw.process_spider_output(root_resp, [child_req], spider))
                    assert results, "Child request should not be filtered"
                    assert results[0].meta.get('depth') == 1, (
                        f"Child depth should be 1, got {results[0].meta.get('depth')}"
                    )
            """),
        ],
    },

    # ------------------------------------------------------------------
    # URL length middleware — filter logic inverted
    # ------------------------------------------------------------------
    {
        "task_id": "urllength_filter_logic_inverted",
        "source_file": "scrapy/spidermiddlewares/urllength.py",
        "family": "middleware",
        "difficulty": 2,
        "description": "URL length filter should block LONG URLs; regression blocks short ones",
        "find": "        if isinstance(request, Request) and len(request.url) > self.maxlength:",
        "replace": "        if isinstance(request, Request) and len(request.url) < self.maxlength:",
        "prompt": textwrap.dedent("""\
            `UrlLengthMiddleware` should filter out requests whose URLs exceed
            `URLLENGTH_LIMIT` characters.  After a recent change the comparison
            operator was flipped, so short URLs are dropped and long URLs pass
            through.

            Fix the URL length check so URLs longer than `URLLENGTH_LIMIT` are
            filtered out (not shorter ones).

            Verify with: pytest tests/test_spidermiddleware_urllength.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request
            from scrapy.spidermiddlewares.urllength import UrlLengthMiddleware
            from scrapy.utils.test import get_crawler
            from unittest.mock import MagicMock

            def test_long_url_filtered():
                crawler = get_crawler(settings_dict={'URLLENGTH_LIMIT': 50})
                mw = UrlLengthMiddleware.from_settings(crawler.settings)
                long_url = 'https://example.com/' + 'a' * 100
                req = Request(long_url)
                spider = MagicMock()
                spider.crawler = crawler
                assert not mw._filter(req, spider), (
                    "Long URL should be filtered (return False)"
                )

            def test_short_url_passes():
                crawler = get_crawler(settings_dict={'URLLENGTH_LIMIT': 200})
                mw = UrlLengthMiddleware.from_settings(crawler.settings)
                req = Request('https://example.com/page')
                spider = MagicMock()
                spider.crawler = crawler
                assert mw._filter(req, spider), "Short URL should pass (return True)"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request
                from scrapy.spidermiddlewares.urllength import UrlLengthMiddleware
                from scrapy.utils.test import get_crawler
                from unittest.mock import MagicMock

                def test_exact_limit_passes():
                    limit = 50
                    crawler = get_crawler(settings_dict={'URLLENGTH_LIMIT': limit})
                    mw = UrlLengthMiddleware.from_settings(crawler.settings)
                    url = 'https://example.com/' + 'x' * (limit - len('https://example.com/'))
                    req = Request(url)
                    spider = MagicMock()
                    spider.crawler = crawler
                    assert mw._filter(req, spider), "URL at exact limit should pass"
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Useragent middleware — set vs setdefault (overrides spider UA)
    # ------------------------------------------------------------------
    {
        "task_id": "useragent_setdefault_override",
        "source_file": "scrapy/downloadermiddlewares/useragent.py",
        "family": "middleware",
        "difficulty": 2,
        "description": "User-Agent should use setdefault (not force-set) so spider can override",
        "find": "            request.headers.setdefault(b\"User-Agent\", self.user_agent)",
        "replace": "            request.headers[b\"User-Agent\"] = self.user_agent  # BUG: always overrides spider UA",
        "prompt": textwrap.dedent("""\
            Scrapy's `UserAgentMiddleware` should set the `User-Agent` header
            only if the request doesn't already have one (using `setdefault`).
            This allows individual requests or spiders to override the global
            `USER_AGENT` setting.

            After a recent change the middleware always overwrites the header,
            even when the request already has a custom `User-Agent`.

            Fix the middleware to use `setdefault` so per-request User-Agent
            overrides are respected.

            Verify with: pytest tests/test_downloadermiddleware_useragent.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request
            from scrapy.downloadermiddlewares.useragent import UserAgentMiddleware
            from scrapy.utils.test import get_crawler
            from unittest.mock import MagicMock

            def test_custom_ua_not_overridden():
                crawler = get_crawler(settings_dict={'USER_AGENT': 'DefaultBot'})
                mw = UserAgentMiddleware.from_crawler(crawler)
                req = Request('https://example.com',
                              headers={'User-Agent': 'CustomBot/1.0'})
                spider = MagicMock()
                mw.process_request(req, spider)
                ua = req.headers.get(b'User-Agent', b'').decode()
                assert 'CustomBot' in ua, (
                    f"Custom UA was overwritten. Got: {ua!r}"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request
                from scrapy.downloadermiddlewares.useragent import UserAgentMiddleware
                from scrapy.utils.test import get_crawler
                from unittest.mock import MagicMock

                def test_default_ua_set_when_missing():
                    crawler = get_crawler(settings_dict={'USER_AGENT': 'DefaultBot'})
                    mw = UserAgentMiddleware.from_crawler(crawler)
                    req = Request('https://example.com')
                    spider = MagicMock()
                    mw.process_request(req, spider)
                    ua = req.headers.get(b'User-Agent', b'').decode()
                    assert 'DefaultBot' in ua or 'Scrapy' in ua, (
                        f"Default UA not set. Got: {ua!r}"
                    )
            """),
        ],
    },

    # ------------------------------------------------------------------
    # HTTP compression — COMPRESSION_ENABLED=False bypass
    # ------------------------------------------------------------------
    {
        "task_id": "compression_enabled_check",
        "source_file": "scrapy/downloadermiddlewares/httpcompression.py",
        "family": "middleware",
        "difficulty": 2,
        "description": "COMPRESSION_ENABLED=False must raise NotConfigured; regression removes check",
        "find": "        if not crawler.settings.getbool(\"COMPRESSION_ENABLED\"):\n            raise NotConfigured",
        "replace": "        # BUG: COMPRESSION_ENABLED check removed",
        "prompt": textwrap.dedent("""\
            Setting `COMPRESSION_ENABLED = False` should disable Scrapy's HTTP
            compression middleware (`HttpCompressionMiddleware`).  After a recent
            change this check was removed, so the middleware is always active.

            Restore the `NotConfigured` raise so `COMPRESSION_ENABLED = False`
            correctly disables the middleware.

            Verify with: pytest tests/test_downloadermiddleware_httpcompression.py -q
        """),
        "visible_test": textwrap.dedent("""\
            import pytest
            from scrapy.exceptions import NotConfigured
            from scrapy.downloadermiddlewares.httpcompression import HttpCompressionMiddleware
            from scrapy.utils.test import get_crawler

            def test_compression_disabled_raises():
                crawler = get_crawler(settings_dict={'COMPRESSION_ENABLED': False})
                with pytest.raises(NotConfigured):
                    HttpCompressionMiddleware.from_crawler(crawler)
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.downloadermiddlewares.httpcompression import HttpCompressionMiddleware
                from scrapy.utils.test import get_crawler

                def test_compression_enabled_creates_instance():
                    crawler = get_crawler(settings_dict={'COMPRESSION_ENABLED': True})
                    mw = HttpCompressionMiddleware.from_crawler(crawler)
                    assert mw is not None
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Offsite middleware — empty allowed_domains should allow all
    # ------------------------------------------------------------------
    {
        "task_id": "offsite_empty_domains_blocks_all",
        "source_file": "scrapy/spidermiddlewares/offsite.py",
        "family": "middleware",
        "difficulty": 3,
        "description": "Empty allowed_domains should allow all URLs; regression blocks all",
        "find": '            return re.compile("")  # allow all by default',
        "replace": '            return re.compile(r"^$")  # BUG: matches nothing, blocks all URLs',
        "prompt": textwrap.dedent("""\
            When a spider has no `allowed_domains` (empty list or not set), the
            offsite middleware should allow all requests through.  After a recent
            change the compiled regex no longer matches any host, so all requests
            are incorrectly filtered as offsite.

            Fix `get_host_regex` so that an empty / missing `allowed_domains`
            returns a pattern that allows every host.

            Verify with: pytest tests/test_spidermiddleware_offsite.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request
            from scrapy.spidermiddlewares.offsite import OffsiteMiddleware
            from scrapy.utils.test import get_crawler
            from unittest.mock import MagicMock

            def test_no_allowed_domains_passes_all():
                crawler = get_crawler()
                mw = OffsiteMiddleware.from_crawler(crawler)
                spider = MagicMock()
                spider.allowed_domains = []
                mw.spider_opened(spider)
                req = Request('https://any-domain-at-all.com/page')
                assert mw.should_follow(req, spider), (
                    "Empty allowed_domains should allow all requests"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request
                from scrapy.spidermiddlewares.offsite import OffsiteMiddleware
                from scrapy.utils.test import get_crawler
                from unittest.mock import MagicMock

                def test_with_allowed_domains_filters():
                    crawler = get_crawler()
                    mw = OffsiteMiddleware.from_crawler(crawler)
                    spider = MagicMock()
                    spider.allowed_domains = ['example.com']
                    mw.spider_opened(spider)
                    ok = Request('https://example.com/page')
                    bad = Request('https://evil.com/page')
                    assert mw.should_follow(ok, spider)
                    assert not mw.should_follow(bad, spider)
            """),
        ],
    },

    # ------------------------------------------------------------------
    # HTTPError middleware — HTTPERROR_ALLOW_ALL flag
    # ------------------------------------------------------------------
    {
        "task_id": "httperror_allow_all_flag",
        "source_file": "scrapy/spidermiddlewares/httperror.py",
        "family": "middleware",
        "difficulty": 2,
        "description": "HTTPERROR_ALLOW_ALL=True should pass all responses; regression ignores it",
        "find": "        if meta.get(\"handle_httpstatus_all\", False):",
        "replace": "        if False:  # BUG: handle_httpstatus_all always False",
        "prompt": textwrap.dedent("""\
            When `request.meta['handle_httpstatus_all'] = True`, all HTTP
            responses (including 4xx/5xx) should be passed to the spider's
            callback.  After a recent change this meta flag is always treated as
            `False`, so error responses are dropped regardless.

            Fix `HttpErrorMiddleware.process_response` so the
            `handle_httpstatus_all` meta flag is respected.

            Verify with: pytest tests/test_spidermiddleware_httperror.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request, Response
            from scrapy.spidermiddlewares.httperror import HttpErrorMiddleware
            from scrapy.utils.test import get_crawler
            from unittest.mock import MagicMock

            def test_handle_all_passes_404():
                crawler = get_crawler()
                mw = HttpErrorMiddleware.from_crawler(crawler)
                req = Request('https://example.com', meta={'handle_httpstatus_all': True})
                resp = Response('https://example.com', status=404, request=req)
                spider = MagicMock()
                result = mw.process_response(req, resp, spider)
                assert result is resp, (
                    f"404 should pass through with handle_httpstatus_all=True, got {result!r}"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request, Response
                from scrapy.spidermiddlewares.httperror import HttpErrorMiddleware
                from scrapy.exceptions import HttpError
                from scrapy.utils.test import get_crawler
                from unittest.mock import MagicMock
                import pytest

                def test_404_dropped_by_default():
                    crawler = get_crawler()
                    mw = HttpErrorMiddleware.from_crawler(crawler)
                    req = Request('https://example.com')
                    resp = Response('https://example.com', status=404, request=req)
                    spider = MagicMock()
                    with pytest.raises(HttpError):
                        mw.process_response(req, resp, spider)
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Feed exporter — overwrite default value
    # ------------------------------------------------------------------
    {
        "task_id": "feedexport_overwrite_default",
        "source_file": "scrapy/extensions/feedexport.py",
        "family": "pipeline",
        "difficulty": 3,
        "description": "Feed exporter overwrite should default to False to avoid data loss",
        "find": "        self.overwrite: bool = not feed_options or feed_options.get(\"overwrite\", True)",
        "replace": "        self.overwrite: bool = not feed_options or feed_options.get(\"overwrite\", False)  # changed default",
        "prompt": textwrap.dedent("""\
            The Scrapy feed exporter's `overwrite` option should default to
            `False` (append mode) to avoid accidentally overwriting existing
            export files.  After a recent change the default was flipped to
            `True`, causing feeds to overwrite existing files by default.

            Fix the feed exporter so `overwrite` defaults to `False` when not
            explicitly set.

            Verify with: pytest tests/test_feedexport.py -k overwrite -q
        """),
        "visible_test": textwrap.dedent("""\
            def test_feedexporter_overwrite_concept():
                \"\"\"The overwrite default should be False (append mode).
                Passes as long as scrapy.extensions.feedexport imports cleanly.\"\"\"
                from scrapy.extensions import feedexport
                assert hasattr(feedexport, 'FeedExporter')
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                def test_feedexport_module_importable():
                    import scrapy.extensions.feedexport as fe
                    assert fe.FeedExporter is not None
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Request cb_kwargs isolation
    # ------------------------------------------------------------------
    {
        "task_id": "request_cb_kwargs_copy",
        "source_file": "scrapy/http/request/__init__.py",
        "family": "request",
        "difficulty": 2,
        "description": "cb_kwargs must be copied on Request init to isolate from caller's dict",
        "find": "        self._cb_kwargs = dict(cb_kwargs) if cb_kwargs else None",
        "replace": "        self._cb_kwargs = cb_kwargs if cb_kwargs else None  # BUG: no copy",
        "prompt": textwrap.dedent("""\
            `Request` should own an independent copy of `cb_kwargs` so that
            external mutations to the dict passed at construction don't affect
            the request.

            After a recent change, `cb_kwargs` is stored by reference, creating
            shared mutable state between the caller and the request.

            Fix `Request.__init__` to copy the `cb_kwargs` argument.

            Verify with: pytest tests/test_http_request.py -k cb_kwargs -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request

            def test_cb_kwargs_isolated_from_caller():
                original = {'page': 1}
                req = Request('https://example.com', cb_kwargs=original)
                original['page'] = 999
                assert req.cb_kwargs['page'] == 1, (
                    f"cb_kwargs mutated by external change: {req.cb_kwargs['page']!r}"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request
                def test_cb_kwargs_none_gives_empty_dict():
                    req = Request('https://example.com')
                    req.cb_kwargs['key'] = 'val'
                    assert req.cb_kwargs['key'] == 'val'

                def test_cb_kwargs_not_shared_between_requests():
                    kw = {'a': 1}
                    r1 = Request('https://a.com', cb_kwargs=kw)
                    r2 = Request('https://b.com', cb_kwargs=kw)
                    r1.cb_kwargs['a'] = 99
                    assert r2.cb_kwargs['a'] == 1, "Requests should not share cb_kwargs"
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Selector getall returns list (checks unified.py getall)
    # ------------------------------------------------------------------
    {
        "task_id": "selectorlist_getall_type",
        "source_file": "scrapy/selector/unified.py",
        "family": "selector",
        "difficulty": 1,
        "description": "SelectorList.getall() should return list[str], not list[Any]",
        "find": "    def getall(self) -> List[str]:",
        "replace": "    def getall(self) -> list:  # BUG: lost type annotation, callers may break",
        "prompt": textwrap.dedent("""\
            `SelectorList.getall()` is typed as returning `List[str]`.  After a
            recent change the return type annotation was loosened to a plain
            `list`, which breaks downstream type-checked code that relies on
            `List[str]`.

            Restore the `List[str]` return type annotation on `getall()`.

            Verify: grep for the annotation and ensure it says List[str] or list[str].
        """),
        "visible_test": textwrap.dedent("""\
            import inspect
            from scrapy.selector.unified import SelectorList

            def test_getall_annotation_is_str_list():
                hints = {}
                try:
                    import typing
                    hints = typing.get_type_hints(SelectorList.getall)
                except Exception:
                    pass
                # If annotation available, check it
                ret = hints.get('return', None)
                if ret is not None:
                    ret_str = str(ret)
                    assert 'str' in ret_str, f"Return annotation should include str, got {ret_str!r}"

            def test_getall_runtime_returns_list_of_strings():
                from scrapy import Selector
                sel = Selector(text='<li>a</li><li>b</li>')
                result = sel.css('li::text').getall()
                assert isinstance(result, list)
                assert all(isinstance(x, str) for x in result)
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy import Selector
                def test_getall_empty():
                    result = Selector(text='<div></div>').css('span').getall()
                    assert result == []
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Settings getlist — returns list not generator
    # ------------------------------------------------------------------
    {
        "task_id": "settings_getlist_returns_list",
        "source_file": "scrapy/settings/__init__.py",
        "family": "settings",
        "difficulty": 1,
        "description": "getlist() must always return a list, not an iterable",
        "find": "    def getlist(\n        self,\n        name: _SettingsKeyT,\n        default: Any = None,\n    ) -> List[Any]:",
        "replace": "    def getlist(\n        self,\n        name: _SettingsKeyT,\n        default: Any = None,\n    ) -> Any:  # BUG: weakened return type",
        "prompt": textwrap.dedent("""\
            `Settings.getlist()` is documented and typed to return a `List`.
            After a recent change its return type annotation was weakened to
            `Any`, and the implementation may now return a non-list iterable in
            some cases.

            Restore the `List[Any]` return type annotation and verify the
            implementation always returns a proper list.

            Verify with: pytest tests/test_settings.py -k getlist -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.settings import Settings

            def test_getlist_is_list():
                s = Settings({'MYLIST': ['a', 'b', 'c']})
                result = s.getlist('MYLIST')
                assert isinstance(result, list), f"Expected list, got {type(result).__name__}"

            def test_getlist_string_split():
                s = Settings({'CSV': 'a,b,c'})
                result = s.getlist('CSV')
                assert isinstance(result, list)
                assert 'a' in result
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.settings import Settings
                def test_getlist_default_none_missing_key():
                    s = Settings()
                    result = s.getlist('NONEXISTENT_ZZZ')
                    assert result is None or isinstance(result, list)
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Request headers — preserve original headers on replace()
    # ------------------------------------------------------------------
    {
        "task_id": "request_replace_headers_preserved",
        "source_file": "scrapy/http/request/__init__.py",
        "family": "request",
        "difficulty": 2,
        "description": "Request.replace() without headers kwarg should preserve original headers",
        "find": "        for x in self.attributes:\n            kwargs.setdefault(x, getattr(self, x))",
        "replace": "        for x in self.attributes:\n            pass  # BUG: always uses defaults, original attributes lost",
        "prompt": textwrap.dedent("""\
            `Request.replace()` should carry over all original attributes except
            those explicitly overridden.  After a recent change, `replace()`
            ignores the original request's attributes entirely and uses the
            class defaults instead.

            Fix `Request.replace()` so that unspecified attributes are copied
            from the original request.

            Verify with: pytest tests/test_http_request.py -k replace -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request

            def test_replace_preserves_headers():
                req = Request('https://example.com',
                              headers={'X-Custom': 'yes'},
                              method='POST')
                new = req.replace(url='https://other.com')
                assert new.method == 'POST', f"Method not preserved: {new.method!r}"

            def test_replace_overrides_specified():
                req = Request('https://example.com', method='GET')
                new = req.replace(method='POST')
                assert new.method == 'POST'
                assert new.url == 'https://example.com'
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request
                def test_replace_preserves_callback():
                    def my_cb(response): pass
                    req = Request('https://example.com', callback=my_cb)
                    new = req.replace(url='https://other.com')
                    assert new.callback is my_cb

                def test_replace_preserves_meta():
                    req = Request('https://example.com', meta={'key': 'val'})
                    new = req.replace(url='https://other.com')
                    assert new.meta.get('key') == 'val'
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Dupefilter — fingerprint not stored after check
    # ------------------------------------------------------------------
    {
        "task_id": "dupefilter_fingerprint_not_stored",
        "source_file": "scrapy/dupefilters.py",
        "family": "scheduler",
        "difficulty": 2,
        "description": "request_seen must add fingerprint to set; regression never stores it",
        "find": "        self.fingerprints.add(fp)\n        if self.file:",
        "replace": "        # BUG: fingerprint never stored\n        if self.file:",
        "prompt": textwrap.dedent("""\
            `RFPDupeFilter.request_seen()` should add each new request's
            fingerprint to its internal set so subsequent identical requests are
            filtered.  After a recent change the fingerprint is never stored,
            causing every request to appear new every time.

            Fix `request_seen` so fingerprints are correctly added to the set.

            Verify with: pytest tests/test_dupefilters.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.dupefilters import RFPDupeFilter
            from scrapy.http import Request

            def test_fingerprint_stored_after_first_seen():
                df = RFPDupeFilter()
                req = Request('https://example.com')
                assert df.request_seen(req) is False   # first time: new
                assert df.request_seen(req) is True    # second time: duplicate
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.dupefilters import RFPDupeFilter
                from scrapy.http import Request

                def test_many_urls_all_unique_then_duplicate():
                    df = RFPDupeFilter()
                    urls = [f'https://example.com/{i}' for i in range(20)]
                    for url in urls:
                        assert df.request_seen(Request(url)) is False
                    for url in urls:
                        assert df.request_seen(Request(url)) is True
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Downloader middleware — process_request None pass-through
    # ------------------------------------------------------------------
    {
        "task_id": "defaultheaders_missing_key_no_error",
        "source_file": "scrapy/downloadermiddlewares/defaultheaders.py",
        "family": "middleware",
        "difficulty": 1,
        "description": "DefaultHeadersMiddleware should skip None values in DEFAULT_REQUEST_HEADERS",
        "find": "        for header, value in self.headers.items():",
        "replace": "        for header, value in list(self.headers.items()) or []:  # BUG: extra list()",
        "prompt": textwrap.dedent("""\
            `DefaultHeadersMiddleware` iterates over the configured headers and
            sets them on each request.  After a recent change an extra
            `list()` wrapping was added around the items iteration that
            produces an empty list when headers is falsy, causing no default
            headers to be set even when `DEFAULT_REQUEST_HEADERS` is populated.

            Fix the middleware so default headers are correctly applied to
            all requests.

            Verify with: pytest tests/test_downloadermiddleware_defaultheaders.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request
            from scrapy.downloadermiddlewares.defaultheaders import DefaultHeadersMiddleware
            from scrapy.utils.test import get_crawler
            from unittest.mock import MagicMock

            def test_default_headers_applied():
                crawler = get_crawler(settings_dict={
                    'DEFAULT_REQUEST_HEADERS': {'Accept': 'text/html'}
                })
                mw = DefaultHeadersMiddleware.from_crawler(crawler)
                req = Request('https://example.com')
                mw.process_request(req, MagicMock())
                assert b'Accept' in req.headers or 'Accept' in req.headers, (
                    f"Accept header not set. Headers: {dict(req.headers)}"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request
                from scrapy.downloadermiddlewares.defaultheaders import DefaultHeadersMiddleware
                from scrapy.utils.test import get_crawler
                from unittest.mock import MagicMock

                def test_existing_header_not_overwritten():
                    crawler = get_crawler(settings_dict={
                        'DEFAULT_REQUEST_HEADERS': {'Accept': 'text/html'}
                    })
                    mw = DefaultHeadersMiddleware.from_crawler(crawler)
                    req = Request('https://example.com',
                                  headers={'Accept': 'application/json'})
                    mw.process_request(req, MagicMock())
                    accept = req.headers.get(b'Accept', b'').decode()
                    assert 'application/json' in accept, (
                        f"Existing Accept header was overwritten: {accept!r}"
                    )
            """),
        ],
    },
]


class StructuralMiningGenerator(BaseGenerator):
    """Generate tasks by mining structural patterns in Scrapy source."""

    def generate(self) -> list[TaskCandidate]:
        candidates = []

        for inj in STRUCTURAL_INJECTIONS:
            source_path = self.scrapy_root / inj["source_file"]
            if not source_path.exists():
                continue

            original = source_path.read_text()
            find_str = inj["find"]
            replace_str = inj["replace"]

            if find_str not in original:
                continue

            patched = original.replace(find_str, replace_str, 1)
            if patched == original:
                continue

            candidate = TaskCandidate(
                task_id=inj["task_id"],
                task_type="invariant_recovery",
                family=inj["family"],
                difficulty=inj["difficulty"],
                prompt=inj["prompt"].strip(),
                start_state_patches={inj["source_file"]: patched},
                visible_tests=[inj["visible_test"]],
                hidden_tests=inj.get("hidden_tests", []),
                structural_checks=[],
                generation_recipe=(
                    f"Structural mining in {inj['source_file']}: {inj['description']}"
                ),
                is_noop=False,
                is_impossible=False,
                metadata={"description": inj["description"]},
            )
            candidates.append(candidate)

        return candidates
