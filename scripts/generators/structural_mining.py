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

    # ------------------------------------------------------------------
    # Retry middleware — off-by-one: < vs <=
    # ------------------------------------------------------------------
    {
        "task_id": "retry_times_off_by_one",
        "source_file": "scrapy/downloadermiddlewares/retry.py",
        "family": "middleware",
        "difficulty": 2,
        "description": "retry should allow up to max_retry_times attempts; regression uses < so last retry is skipped",
        "find": "    if retry_times <= max_retry_times:",
        "replace": "    if retry_times < max_retry_times:  # BUG: off-by-one, skips last allowed retry",
        "prompt": textwrap.dedent("""\
            Scrapy's retry middleware should retry a request up to
            `RETRY_TIMES` times (inclusive).  After a recent change the
            comparison was changed from `<=` to `<`, so one fewer retry
            is performed than configured.

            Fix the condition so requests are retried up to and including
            `RETRY_TIMES` attempts.

            Verify with: pytest tests/test_downloadermiddleware_retry.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from unittest.mock import MagicMock, patch
            from scrapy.http import Request, Response
            from scrapy.downloadermiddlewares.retry import RetryMiddleware
            from scrapy.utils.test import get_crawler

            def test_retry_uses_full_quota():
                crawler = get_crawler(settings_dict={'RETRY_TIMES': 2, 'RETRY_HTTP_CODES': [500]})
                mw = RetryMiddleware.from_crawler(crawler)
                req = Request('https://example.com')
                spider = MagicMock()
                spider.crawler = crawler
                # Simulate 2 prior retries — next attempt should still be allowed
                req.meta['retry_times'] = 1
                resp = Response('https://example.com', status=500, request=req)
                result = mw.process_response(req, resp, spider)
                assert isinstance(result, Request), (
                    "Should retry (attempt 2 of 2 is still within quota)"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from unittest.mock import MagicMock
                from scrapy.http import Request, Response
                from scrapy.downloadermiddlewares.retry import RetryMiddleware
                from scrapy.utils.test import get_crawler

                def test_no_retry_after_quota_exhausted():
                    crawler = get_crawler(settings_dict={'RETRY_TIMES': 2, 'RETRY_HTTP_CODES': [500]})
                    mw = RetryMiddleware.from_crawler(crawler)
                    req = Request('https://example.com', meta={'retry_times': 2})
                    spider = MagicMock()
                    spider.crawler = crawler
                    resp = Response('https://example.com', status=500, request=req)
                    result = mw.process_response(req, resp, spider)
                    assert isinstance(result, Response), (
                        "Should give up after quota exhausted"
                    )
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Robots.txt middleware — allowed check inverted
    # ------------------------------------------------------------------
    {
        "task_id": "robotstxt_allowed_inverted",
        "source_file": "scrapy/downloadermiddlewares/robotstxt.py",
        "family": "middleware",
        "difficulty": 2,
        "description": "robots.txt should block disallowed URLs; regression blocks allowed ones",
        "find": "        if not rp.allowed(request.url, useragent):",
        "replace": "        if rp.allowed(request.url, useragent):  # BUG: logic inverted, blocks allowed URLs",
        "prompt": textwrap.dedent("""\
            The robots.txt middleware should raise `IgnoreRequest` only for
            URLs that are *not* allowed by the rules.  After a recent change
            the condition was inverted: requests that are allowed are now
            blocked and vice versa.

            Fix the robots.txt check so disallowed URLs are ignored and
            allowed URLs pass through.

            Verify with: pytest tests/test_downloadermiddleware_robotstxt.py -q
        """),
        "visible_test": textwrap.dedent("""\
            import pytest
            from unittest.mock import MagicMock, patch
            from scrapy.exceptions import IgnoreRequest
            from scrapy.http import Request
            from scrapy.downloadermiddlewares.robotstxt import RobotsTxtMiddleware
            from scrapy.utils.test import get_crawler

            def test_disallowed_raises_ignore():
                rp = MagicMock()
                rp.allowed.return_value = False
                crawler = get_crawler(settings_dict={'ROBOTSTXT_OBEY': True})
                mw = RobotsTxtMiddleware.from_crawler(crawler)
                mw._default_useragent = b'Scrapy'
                req = Request('https://example.com/disallowed')
                req.meta['robotstxt_rule'] = None
                with pytest.raises(IgnoreRequest):
                    mw.process_request_2(rp, req, MagicMock())

            def test_allowed_passes_through():
                rp = MagicMock()
                rp.allowed.return_value = True
                crawler = get_crawler(settings_dict={'ROBOTSTXT_OBEY': True})
                mw = RobotsTxtMiddleware.from_crawler(crawler)
                mw._default_useragent = b'Scrapy'
                req = Request('https://example.com/allowed')
                result = mw.process_request_2(rp, req, MagicMock())
                assert result is None, "Allowed request should pass (return None)"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from unittest.mock import MagicMock
                from scrapy.http import Request
                from scrapy.downloadermiddlewares.robotstxt import RobotsTxtMiddleware
                from scrapy.utils.test import get_crawler

                def test_allowed_returns_none_not_exception():
                    rp = MagicMock()
                    rp.allowed.return_value = True
                    crawler = get_crawler(settings_dict={'ROBOTSTXT_OBEY': True})
                    mw = RobotsTxtMiddleware.from_crawler(crawler)
                    mw._default_useragent = b'Scrapy'
                    req = Request('https://example.com/page')
                    result = mw.process_request_2(rp, req, MagicMock())
                    assert result is None
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Request method uppercasing dropped
    # ------------------------------------------------------------------
    {
        "task_id": "request_method_not_uppercased",
        "source_file": "scrapy/http/request/__init__.py",
        "family": "request",
        "difficulty": 1,
        "description": "Request.method must be uppercased; regression stores it as-is",
        "find": "        self.method = str(method).upper()",
        "replace": '        self.method = str(method)  # BUG: no longer uppercased',
        "prompt": textwrap.dedent("""\
            `Request` always normalises the HTTP method to uppercase
            (e.g. `"get"` → `"GET"`).  After a recent change the
            `.upper()` call was removed, so mixed-case methods are stored
            as provided and HTTP comparisons in middleware break.

            Restore the uppercasing so `request.method` is always uppercase.

            Verify with: pytest tests/test_http_request.py -k method -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request

            def test_lowercase_method_is_uppercased():
                req = Request('https://example.com', method='get')
                assert req.method == 'GET', f"Expected GET, got {req.method!r}"

            def test_mixed_case_method_is_uppercased():
                req = Request('https://example.com', method='Post')
                assert req.method == 'POST', f"Expected POST, got {req.method!r}"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request
                def test_default_method_is_get():
                    req = Request('https://example.com')
                    assert req.method == 'GET'

                def test_delete_uppercased():
                    req = Request('https://example.com', method='delete')
                    assert req.method == 'DELETE'
            """),
        ],
    },

    # ------------------------------------------------------------------
    # HttpCache middleware — HTTPCACHE_ENABLED ignored
    # ------------------------------------------------------------------
    {
        "task_id": "httpcache_enabled_check_inverted",
        "source_file": "scrapy/downloadermiddlewares/httpcache.py",
        "family": "middleware",
        "difficulty": 2,
        "description": "HTTPCACHE_ENABLED=False should raise NotConfigured; regression does the opposite",
        "find": "        if not settings.getbool(\"HTTPCACHE_ENABLED\"):\n            raise NotConfigured",
        "replace": "        if settings.getbool(\"HTTPCACHE_ENABLED\"):  # BUG: raises when enabled\n            raise NotConfigured",
        "prompt": textwrap.dedent("""\
            `HttpCacheMiddleware` should raise `NotConfigured` (and thus be
            disabled) when `HTTPCACHE_ENABLED = False`.  After a recent
            change the condition was inverted: the middleware now raises
            when caching *is* enabled and silently activates when it is
            disabled.

            Fix the check so `HTTPCACHE_ENABLED = False` correctly disables
            the middleware.

            Verify with: pytest tests/test_downloadermiddleware_httpcache.py -q
        """),
        "visible_test": textwrap.dedent("""\
            import pytest
            from scrapy.exceptions import NotConfigured
            from scrapy.downloadermiddlewares.httpcache import HttpCacheMiddleware
            from scrapy.utils.test import get_crawler

            def test_disabled_raises_not_configured():
                crawler = get_crawler(settings_dict={'HTTPCACHE_ENABLED': False})
                with pytest.raises(NotConfigured):
                    HttpCacheMiddleware.from_crawler(crawler)

            def test_enabled_does_not_raise():
                crawler = get_crawler(settings_dict={
                    'HTTPCACHE_ENABLED': True,
                    'HTTPCACHE_DIR': '/tmp/test_cache'
                })
                mw = HttpCacheMiddleware.from_crawler(crawler)
                assert mw is not None
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.downloadermiddlewares.httpcache import HttpCacheMiddleware
                from scrapy.utils.test import get_crawler

                def test_enabled_true_creates_middleware():
                    crawler = get_crawler(settings_dict={
                        'HTTPCACHE_ENABLED': True,
                        'HTTPCACHE_DIR': '/tmp/test_cache_hidden'
                    })
                    mw = HttpCacheMiddleware.from_crawler(crawler)
                    assert hasattr(mw, 'policy')
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Response replace — drops original attributes
    # ------------------------------------------------------------------
    {
        "task_id": "response_replace_drops_attributes",
        "source_file": "scrapy/http/response/__init__.py",
        "family": "response",
        "difficulty": 2,
        "description": "Response.replace() without kwargs should preserve all original attributes",
        "find": "        for x in self.attributes:\n            kwargs.setdefault(x, getattr(self, x))",
        "replace": "        for x in self.attributes:\n            pass  # BUG: attributes never carried over",
        "prompt": textwrap.dedent("""\
            `Response.replace()` should copy all attributes from the original
            response except those explicitly overridden in the call.  After
            a recent change none of the original attributes are preserved —
            calling `resp.replace(status=404)` produces a response with
            default values for url, headers, body, etc.

            Fix `Response.replace()` so unspecified attributes are preserved.

            Verify with: pytest tests/test_http_response.py -k replace -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Response

            def test_replace_preserves_body():
                resp = Response('https://example.com', body=b'hello', status=200)
                new = resp.replace(status=404)
                assert new.body == b'hello', f"Body not preserved: {new.body!r}"
                assert new.status == 404
                assert new.url == 'https://example.com'

            def test_replace_preserves_headers():
                resp = Response('https://example.com',
                                headers={'Content-Type': 'text/html'}, status=200)
                new = resp.replace(status=301)
                assert new.headers.get('Content-Type') == b'text/html'
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Response
                def test_replace_url_only():
                    resp = Response('https://a.com', body=b'data', status=200)
                    new = resp.replace(url='https://b.com')
                    assert new.url == 'https://b.com'
                    assert new.body == b'data'
                    assert new.status == 200
            """),
        ],
    },

    # ------------------------------------------------------------------
    # SpiderLoader.list() returns all spider names
    # ------------------------------------------------------------------
    {
        "task_id": "spiderloader_list_wrong_return",
        "source_file": "scrapy/spiderloader.py",
        "family": "spider",
        "difficulty": 1,
        "description": "SpiderLoader.list() must return all spider names; regression returns empty",
        "find": "        return list(self._spiders.keys())",
        "replace": "        return []  # BUG: always returns empty list",
        "prompt": textwrap.dedent("""\
            `SpiderLoader.list()` should return the names of all available
            spiders.  After a recent change it always returns an empty list,
            so `scrapy list` shows nothing and `CrawlerProcess` cannot
            discover spiders by name.

            Fix `list()` so it returns the names of all registered spiders.

            Verify with: pytest tests/test_spiderloader.py -q
        """),
        "visible_test": textwrap.dedent("""\
            import sys
            import types
            from scrapy.spiderloader import SpiderLoader
            from scrapy.spiders import Spider
            from scrapy.utils.test import get_crawler

            class MySpider(Spider):
                name = 'myspider'

            def test_list_returns_spider_names(tmp_path, monkeypatch):
                mod = types.ModuleType('mymod')
                mod.MySpider = MySpider
                monkeypatch.setitem(sys.modules, 'mymod', mod)
                crawler = get_crawler(settings_dict={'SPIDER_MODULES': ['mymod']})
                loader = SpiderLoader.from_crawler(crawler)
                names = loader.list()
                assert 'myspider' in names, f"Expected 'myspider' in {names}"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                import sys, types
                from scrapy.spiderloader import SpiderLoader
                from scrapy.spiders import Spider
                from scrapy.utils.test import get_crawler

                class Alpha(Spider):
                    name = 'alpha'
                class Beta(Spider):
                    name = 'beta'

                def test_list_returns_all_names(monkeypatch):
                    mod = types.ModuleType('twomod')
                    mod.Alpha = Alpha
                    mod.Beta = Beta
                    monkeypatch.setitem(sys.modules, 'twomod', mod)
                    crawler = get_crawler(settings_dict={'SPIDER_MODULES': ['twomod']})
                    loader = SpiderLoader.from_crawler(crawler)
                    names = loader.list()
                    assert set(names) == {'alpha', 'beta'}
            """),
        ],
    },

    # ------------------------------------------------------------------
    # CoreStats — elapsed_time not computed
    # ------------------------------------------------------------------
    {
        "task_id": "corestats_elapsed_time_missing",
        "source_file": "scrapy/extensions/corestats.py",
        "family": "pipeline",
        "difficulty": 2,
        "description": "elapsed_time_seconds must be computed from start and finish time",
        "find": "        elapsed_time = finish_time - self.start_time\n        elapsed_time_seconds = elapsed_time.total_seconds()",
        "replace": "        elapsed_time_seconds = 0.0  # BUG: always zero",
        "prompt": textwrap.dedent("""\
            `CoreStats` records `elapsed_time_seconds` in spider stats by
            subtracting `start_time` from `finish_time`.  After a recent
            change this is always set to `0.0` regardless of how long the
            crawl took.

            Fix `spider_closed` so `elapsed_time_seconds` reflects the
            actual crawl duration.

            Verify with: pytest tests/test_extension_corestats.py -q
        """),
        "visible_test": textwrap.dedent("""\
            import time
            from datetime import datetime, timezone, timedelta
            from unittest.mock import MagicMock, patch
            from scrapy.extensions.corestats import CoreStats

            def test_elapsed_time_is_nonzero():
                stats = {}
                mock_stats = MagicMock()
                mock_stats.set_value.side_effect = lambda k, v, **kw: stats.update({k: v})

                ext = CoreStats(mock_stats)
                spider = MagicMock()

                start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
                finish = datetime(2024, 1, 1, 0, 0, 5, tzinfo=timezone.utc)

                ext.start_time = start
                with patch('scrapy.extensions.corestats.datetime') as mock_dt:
                    mock_dt.now.return_value = finish
                    ext.spider_closed(spider, 'finished')

                elapsed = stats.get('elapsed_time_seconds', 0)
                assert elapsed == 5.0, f"Expected 5.0, got {elapsed}"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from datetime import datetime, timezone
                from unittest.mock import MagicMock, patch
                from scrapy.extensions.corestats import CoreStats

                def test_elapsed_matches_actual_duration():
                    stats = {}
                    mock_stats = MagicMock()
                    mock_stats.set_value.side_effect = lambda k, v, **kw: stats.update({k: v})
                    ext = CoreStats(mock_stats)
                    ext.start_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
                    finish = datetime(2024, 1, 1, 0, 2, 30, tzinfo=timezone.utc)
                    with patch('scrapy.extensions.corestats.datetime') as mock_dt:
                        mock_dt.now.return_value = finish
                        ext.spider_closed(MagicMock(), 'finished')
                    assert stats.get('elapsed_time_seconds') == 150.0
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Stats collector — inc_value does not default start from 0
    # ------------------------------------------------------------------
    {
        "task_id": "stats_inc_value_wrong_default",
        "source_file": "scrapy/statscollectors.py",
        "family": "pipeline",
        "difficulty": 1,
        "description": "inc_value must start count from 0 if key missing; regression starts from None",
        "find": "    def inc_value(\n        self,\n        key: str,\n        count: int = 1,\n        start: int = 0,\n        spider: Optional[Spider] = None,\n    ) -> None:\n        d = self._stats\n        d[key] = d.setdefault(key, start) + count",
        "replace": "    def inc_value(\n        self,\n        key: str,\n        count: int = 1,\n        start: int = 0,\n        spider: Optional[Spider] = None,\n    ) -> None:\n        d = self._stats\n        d[key] = d.get(key, None) + count  # BUG: crashes if key absent (None + int)",
        "prompt": textwrap.dedent("""\
            `MemoryStatsCollector.inc_value()` should initialise a missing
            counter to `start` (default 0) before incrementing.  After a
            recent change it uses `dict.get(key, None)` which causes a
            `TypeError` the first time a new stat key is incremented.

            Fix `inc_value` so missing keys are initialised to `start`
            before the increment.

            Verify with: pytest tests/test_stats.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.statscollectors import MemoryStatsCollector
            from unittest.mock import MagicMock

            def test_inc_new_key_starts_at_one():
                crawler = MagicMock()
                stats = MemoryStatsCollector(crawler)
                stats.inc_value('pages_crawled')
                assert stats.get_value('pages_crawled') == 1

            def test_inc_existing_key_accumulates():
                crawler = MagicMock()
                stats = MemoryStatsCollector(crawler)
                stats.inc_value('count', 3)
                stats.inc_value('count', 2)
                assert stats.get_value('count') == 5
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.statscollectors import MemoryStatsCollector
                from unittest.mock import MagicMock

                def test_inc_with_custom_start():
                    crawler = MagicMock()
                    stats = MemoryStatsCollector(crawler)
                    stats.inc_value('x', count=1, start=10)
                    assert stats.get_value('x') == 11
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Link extractor — unique flag not deduplicated
    # ------------------------------------------------------------------
    {
        "task_id": "linkextractor_unique_not_enforced",
        "source_file": "scrapy/linkextractors/__init__.py",
        "family": "spider",
        "difficulty": 2,
        "description": "FilteringLinkExtractor must deduplicate links when unique=True",
        "find": "        if self.unique:\n            return unique_list(links)",
        "replace": "        if self.unique:\n            return links  # BUG: deduplication skipped",
        "prompt": textwrap.dedent("""\
            `FilteringLinkExtractor` with `unique=True` (the default) should
            return each link only once.  After a recent change the
            deduplication step was skipped so duplicate links appear in the
            output even when `unique=True`.

            Fix the extractor so duplicate links are removed when `unique=True`.

            Verify with: pytest tests/test_linkextractors.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.linkextractors import LinkExtractor
            from scrapy.http import HtmlResponse

            def test_unique_removes_duplicates():
                response = HtmlResponse(
                    url='https://example.com',
                    body=b'<a href="/page">A</a><a href="/page">B</a>',
                )
                le = LinkExtractor(unique=True)
                links = le.extract_links(response)
                urls = [l.url for l in links]
                assert len(urls) == len(set(urls)), f"Duplicate URLs: {urls}"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.linkextractors import LinkExtractor
                from scrapy.http import HtmlResponse

                def test_non_unique_allows_duplicates():
                    response = HtmlResponse(
                        url='https://example.com',
                        body=b'<a href="/p">A</a><a href="/p">B</a>',
                    )
                    le = LinkExtractor(unique=False)
                    links = le.extract_links(response)
                    assert len(links) == 2
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Redirect middleware — ttl not decremented
    # ------------------------------------------------------------------
    {
        "task_id": "redirect_ttl_not_decremented",
        "source_file": "scrapy/downloadermiddlewares/redirect.py",
        "family": "middleware",
        "difficulty": 3,
        "description": "redirect_ttl must decrement on each hop; regression never decrements",
        "find": "        ttl = request.meta.setdefault(\"redirect_ttl\", self.max_redirect_times)\n",
        "replace": "        ttl = self.max_redirect_times  # BUG: ttl never decremented across hops\n",
        "prompt": textwrap.dedent("""\
            The redirect middleware uses `redirect_ttl` in request meta as a
            countdown to limit total redirects.  After a recent change the
            TTL is always reset to `REDIRECT_MAX_TIMES` on every hop instead
            of being carried over from the previous request's meta, so
            infinite redirect chains are no longer detected.

            Fix the TTL logic so it decrements across hops and redirects are
            correctly limited.

            Verify with: pytest tests/test_downloadermiddleware_redirect.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request, Response
            from scrapy.downloadermiddlewares.redirect import RedirectMiddleware
            from scrapy.utils.test import get_crawler
            from unittest.mock import MagicMock

            def test_ttl_carried_across_hops():
                crawler = get_crawler(settings_dict={'REDIRECT_MAX_TIMES': 3})
                mw = RedirectMiddleware.from_crawler(crawler)
                req = Request('https://example.com',
                              meta={'redirect_ttl': 1, 'redirect_times': 2})
                resp = Response('https://b.com', status=301,
                                headers={'Location': 'https://c.com'},
                                request=req)
                result = mw.process_response(req, resp, MagicMock())
                # ttl=1 and redirects > 0: should give up
                assert isinstance(result, Response), (
                    "Should stop redirecting when TTL is exhausted"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request, Response
                from scrapy.downloadermiddlewares.redirect import RedirectMiddleware
                from scrapy.utils.test import get_crawler
                from unittest.mock import MagicMock

                def test_first_redirect_sets_ttl():
                    crawler = get_crawler(settings_dict={'REDIRECT_MAX_TIMES': 5})
                    mw = RedirectMiddleware.from_crawler(crawler)
                    req = Request('https://example.com')
                    resp = Response('https://other.com', status=302,
                                    headers={'Location': 'https://final.com'},
                                    request=req)
                    result = mw.process_response(req, resp, MagicMock())
                    assert isinstance(result, Request)
                    assert 'redirect_ttl' in result.meta
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Settings.getwithbase — merges base dict incorrectly
    # ------------------------------------------------------------------
    {
        "task_id": "settings_getwithbase_merge_order",
        "source_file": "scrapy/settings/__init__.py",
        "family": "settings",
        "difficulty": 3,
        "description": "getwithbase must put BASE entries first so user entries take priority",
        "find": "        compbs = BaseSettings()\n        compbs.update(self[name + \"_BASE\"], priority=\"default\")\n        compbs.update(self[name], priority=\"default\")",
        "replace": "        compbs = BaseSettings()\n        compbs.update(self[name], priority=\"default\")\n        compbs.update(self[name + \"_BASE\"], priority=\"default\")  # BUG: base overwrites user",
        "prompt": textwrap.dedent("""\
            `Settings.getwithbase('ITEM_PIPELINES')` merges the base dict
            (`ITEM_PIPELINES_BASE`) with the user-configured dict
            (`ITEM_PIPELINES`) by applying BASE first and then the user
            dict, so user settings override base.  After a recent change
            the order was swapped: the base is applied last and overwrites
            user entries.

            Fix `getwithbase` so the base dict entries can be overridden by
            user-configured entries.

            Verify with: pytest tests/test_settings.py -k getwithbase -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.settings import Settings

            def test_user_value_overrides_base():
                s = Settings()
                s.set('MY_BASE', {'a': 1, 'b': 2})
                s.set('MY', {'b': 99})
                merged = s.getwithbase('MY')
                assert merged['b'] == 99, (
                    f"User value should override base, got {merged['b']}"
                )
                assert merged['a'] == 1, "Base entry should be present"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.settings import Settings

                def test_base_only_entries_present():
                    s = Settings()
                    s.set('PIPE_BASE', {'core': 100})
                    s.set('PIPE', {'custom': 200})
                    merged = s.getwithbase('PIPE')
                    assert 'core' in merged
                    assert 'custom' in merged

                def test_user_can_disable_base_entry():
                    s = Settings()
                    s.set('PIPE_BASE', {'core': 100})
                    s.set('PIPE', {'core': None})
                    merged = s.getwithbase('PIPE')
                    assert merged.get('core') is None
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Spider.logger property — uses wrong name
    # ------------------------------------------------------------------
    {
        "task_id": "spider_logger_wrong_name",
        "source_file": "scrapy/spiders/__init__.py",
        "family": "spider",
        "difficulty": 1,
        "description": "spider.logger must use spider.name; regression uses class name",
        "find": "        return logging.getLogger(self.name)",
        "replace": '        return logging.getLogger(self.__class__.__name__)  # BUG: uses class name not spider.name',
        "prompt": textwrap.dedent("""\
            Each spider's `logger` property should return a logger named
            after `spider.name` so log records can be filtered by spider
            name.  After a recent change it uses `self.__class__.__name__`
            instead, breaking log filtering for spiders whose class name
            differs from their `name` attribute.

            Fix the `logger` property to use `self.name`.

            Verify with: pytest tests/test_spider.py -k logger -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.spiders import Spider

            class MySpider(Spider):
                name = 'my_spider'
                start_urls = []

            def test_logger_named_after_spider_name():
                spider = MySpider.from_settings(__import__('scrapy').settings.Settings())
                assert spider.logger.name == 'my_spider', (
                    f"Logger name should be spider.name, got {spider.logger.name!r}"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.spiders import Spider
                class WeirdNameSpider(Spider):
                    name = 'weird_name'
                    start_urls = []

                def test_logger_name_not_class_name():
                    import scrapy
                    spider = WeirdNameSpider.from_settings(scrapy.settings.Settings())
                    assert spider.logger.name != 'WeirdNameSpider'
                    assert spider.logger.name == 'weird_name'
            """),
        ],
    },

    # ------------------------------------------------------------------
    # TextResponse.follow — encoding lost
    # ------------------------------------------------------------------
    {
        "task_id": "textresponse_follow_encoding_lost",
        "source_file": "scrapy/http/response/text.py",
        "family": "response",
        "difficulty": 2,
        "description": "TextResponse.follow must pass response encoding to child request",
        "find": "        encoding = self.encoding if encoding is None else encoding\n        return super().follow(",
        "replace": "        encoding = None  # BUG: encoding always None, ignores response charset\n        return super().follow(",
        "prompt": textwrap.dedent("""\
            `TextResponse.follow(url)` should resolve relative URLs against
            the current response's URL.  After a recent change the
            `urljoin` call was removed, so relative hrefs like `'/next'`
            are passed directly to `Request`, producing invalid absolute
            URLs.

            Fix `follow` so relative URLs are resolved against
            `self.url` before creating the `Request`.

            Verify with: pytest tests/test_http_response.py -k follow -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http.response.text import TextResponse

            def test_follow_relative_url_resolved():
                resp = TextResponse(
                    url='https://example.com/section/',
                    body=b'<a href="page.html">link</a>',
                    encoding='utf-8',
                )
                req = resp.follow('page.html')
                assert req.url == 'https://example.com/section/page.html', (
                    f"Unexpected URL: {req.url!r}"
                )

            def test_follow_absolute_url_unchanged():
                resp = TextResponse(
                    url='https://example.com/',
                    body=b'',
                    encoding='utf-8',
                )
                req = resp.follow('https://other.com/page')
                assert req.url == 'https://other.com/page'
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http.response.text import TextResponse

                def test_follow_root_relative():
                    resp = TextResponse(
                        url='https://example.com/a/b/c',
                        body=b'',
                        encoding='utf-8',
                    )
                    req = resp.follow('/new/path')
                    assert req.url == 'https://example.com/new/path'
            """),
        ],
    },

    # ------------------------------------------------------------------
    # LinkExtractor unique deduplication in lxmlhtml
    # ------------------------------------------------------------------
    {
        "task_id": "linkextractor_unique_not_enforced",
        "source_file": "scrapy/linkextractors/lxmlhtml.py",
        "family": "spider",
        "difficulty": 2,
        "description": "LxmlLinkExtractor must deduplicate links when unique=True",
        "find": "        if self.unique:\n            return unique_list(links, key=self.link_key)",
        "replace": "        if self.unique:\n            return links  # BUG: deduplication skipped",
        "prompt": textwrap.dedent("""\
            You notice that `Selector.css()` has been accidentally
            overwritten and now returns the raw XPath translation string
            instead of a `SelectorList`.  All CSS-based scraping is broken.

            Restore `Selector.css()` so it returns a proper `SelectorList`
            by calling `self.xpath()` with the translated XPath expression.

            Verify with: pytest tests/test_selector.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy import Selector

            def test_css_returns_selector_list():
                sel = Selector(text='<div class="item"><p>Hello</p></div>')
                result = sel.css('div.item p')
                assert hasattr(result, 'getall'), (
                    f"Expected SelectorList, got {type(result).__name__}"
                )
                texts = result.css('::text').getall()
                assert 'Hello' in texts
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy import Selector
                def test_css_multiple_results():
                    sel = Selector(text='<ul><li>a</li><li>b</li><li>c</li></ul>')
                    items = sel.css('li::text').getall()
                    assert items == ['a', 'b', 'c']
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Stats inc_value — default start ignored
    # ------------------------------------------------------------------
    {
        "task_id": "stats_inc_value_wrong_default",
        "source_file": "scrapy/statscollectors.py",
        "family": "pipeline",
        "difficulty": 1,
        "description": "inc_value must start from 0 for new keys; regression crashes on None + int",
        "find": "    def inc_value(\n        self, key: str, count: int = 1, start: int = 0, spider: Optional[Spider] = None\n    ) -> None:\n        d = self._stats\n        d[key] = d.setdefault(key, start) + count",
        "replace": "    def inc_value(\n        self, key: str, count: int = 1, start: int = 0, spider: Optional[Spider] = None\n    ) -> None:\n        d = self._stats\n        d[key] = d.get(key, None) + count  # BUG: crashes on new keys (None + int)",
        "prompt": textwrap.dedent("""\
            `MemoryStatsCollector.inc_value()` should initialise a missing
            counter to `start` (default `0`) before incrementing.  After a
            recent change it uses `dict.get(key, None)` which raises a
            `TypeError` the first time any new stat key is incremented.

            Fix `inc_value` so missing keys are initialised to `start`
            before the increment.

            Verify with: pytest tests/test_stats.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.statscollectors import MemoryStatsCollector
            from unittest.mock import MagicMock

            def test_inc_new_key_starts_at_one():
                crawler = MagicMock()
                stats = MemoryStatsCollector(crawler)
                stats.inc_value('pages_crawled')
                assert stats.get_value('pages_crawled') == 1

            def test_inc_existing_key_accumulates():
                crawler = MagicMock()
                stats = MemoryStatsCollector(crawler)
                stats.inc_value('count', 3)
                stats.inc_value('count', 2)
                assert stats.get_value('count') == 5
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.statscollectors import MemoryStatsCollector
                from unittest.mock import MagicMock

                def test_inc_with_custom_start():
                    crawler = MagicMock()
                    stats = MemoryStatsCollector(crawler)
                    stats.inc_value('x', count=1, start=10)
                    assert stats.get_value('x') == 11
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Settings.getwithbase — merge order swapped
    # ------------------------------------------------------------------
    {
        "task_id": "settings_getwithbase_merge_order",
        "source_file": "scrapy/settings/__init__.py",
        "family": "settings",
        "difficulty": 3,
        "description": "getwithbase must apply BASE first so user entries win",
        "find": "        compbs = BaseSettings()\n        compbs.update(self[name + \"_BASE\"])\n        compbs.update(self[name])",
        "replace": "        compbs = BaseSettings()\n        compbs.update(self[name])\n        compbs.update(self[name + \"_BASE\"])  # BUG: base overwrites user",
        "prompt": textwrap.dedent("""\
            `Settings.getwithbase('ITEM_PIPELINES')` merges the base dict
            (`ITEM_PIPELINES_BASE`) with the user dict (`ITEM_PIPELINES`),
            applying BASE first so user entries can override it.  After a
            recent change the order was swapped: the base is applied last
            and silently overwrites user-configured values.

            Fix `getwithbase` so user entries take priority over BASE entries.

            Verify with: pytest tests/test_settings.py -k getwithbase -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.settings import Settings

            def test_user_value_overrides_base():
                s = Settings()
                s.set('MY_BASE', {'a': 1, 'b': 2})
                s.set('MY', {'b': 99})
                merged = s.getwithbase('MY')
                assert merged['b'] == 99, (
                    f"User value should override base, got {merged['b']}"
                )
                assert merged['a'] == 1, "Base-only entry should be present"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.settings import Settings

                def test_base_only_entries_present():
                    s = Settings()
                    s.set('PIPE_BASE', {'core': 100})
                    s.set('PIPE', {'custom': 200})
                    merged = s.getwithbase('PIPE')
                    assert 'core' in merged
                    assert 'custom' in merged

                def test_user_can_set_none_to_disable():
                    s = Settings()
                    s.set('PIPE_BASE', {'core': 100})
                    s.set('PIPE', {'core': None})
                    merged = s.getwithbase('PIPE')
                    assert merged.get('core') is None
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Spider.logger uses wrong name
    # ------------------------------------------------------------------
    {
        "task_id": "spider_logger_wrong_name",
        "source_file": "scrapy/spiders/__init__.py",
        "family": "spider",
        "difficulty": 1,
        "description": "spider.logger must use spider.name not class name",
        "find": "        logger = logging.getLogger(self.name)",
        "replace": '        logger = logging.getLogger(self.__class__.__name__)  # BUG: uses class name',
        "prompt": textwrap.dedent("""\
            Each spider's `logger` property should return a logger named
            after `spider.name` so log records can be filtered by spider
            name at runtime.  After a recent change it uses
            `self.__class__.__name__` instead, breaking log filtering for
            spiders whose class name differs from their `name` attribute.

            Fix the `logger` property to use `self.name`.

            Verify with: pytest tests/test_spider.py -k logger -q
        """),
        "visible_test": textwrap.dedent("""\
            import scrapy

            class MySpider(scrapy.Spider):
                name = 'my_spider'
                start_urls = []

            def test_logger_named_after_spider_name():
                spider = MySpider.from_settings(scrapy.settings.Settings())
                assert spider.logger.logger.name == 'my_spider', (
                    f"Logger name should be spider.name, got {spider.logger.logger.name!r}"
                )
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                import scrapy

                class WeirdName(scrapy.Spider):
                    name = 'weird_name'
                    start_urls = []

                def test_logger_not_class_name():
                    spider = WeirdName.from_settings(scrapy.settings.Settings())
                    assert spider.logger.logger.name != 'WeirdName'
                    assert spider.logger.logger.name == 'weird_name'
            """),
        ],
    },
    # ------------------------------------------------------------------
    # Scheduler has_pending_requests always False
    # ------------------------------------------------------------------
    {
        "task_id": "scheduler_has_pending_always_false",
        "source_file": "scrapy/core/scheduler.py",
        "family": "scheduler",
        "difficulty": 2,
        "description": "has_pending_requests must return True when queue is non-empty",
        "find": "    def has_pending_requests(self) -> bool:\n        return len(self) > 0",
        "replace": "    def has_pending_requests(self) -> bool:\n        return False  # BUG: engine never processes queued requests",
        "prompt": textwrap.dedent("""\
            `Scheduler.has_pending_requests()` should return `True` when
            there are queued requests waiting to be processed.  After a
            recent change it always returns `False`, so the engine
            immediately considers the crawl finished even with a non-empty
            queue.

            Fix `has_pending_requests` so it correctly reports whether the
            scheduler has queued requests.

            Verify with: pytest tests/test_scheduler.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from unittest.mock import MagicMock, patch
            from scrapy.core.scheduler import Scheduler
            from scrapy.http import Request
            from scrapy.utils.test import get_crawler

            def test_has_pending_after_enqueue(tmp_path):
                crawler = get_crawler(settings_dict={
                    'SCHEDULER_DEBUG': False,
                    'JOBDIR': None,
                    'DUPEFILTER_CLASS': 'scrapy.dupefilters.BaseDupeFilter',
                })
                from scrapy.dupefilters import RFPDupeFilter
                scheduler = Scheduler(
                    dupefilter=RFPDupeFilter(),
                    jobdir=None,
                    dqclass=None,
                    mqclass=None,
                    logunser=False,
                    stats=MagicMock(),
                    pqclass=None,
                    crawler=crawler,
                )
                spider = MagicMock()
                scheduler.open(spider)
                request = Request("https://example.com")
                assert scheduler.enqueue_request(request) is True
                assert scheduler.has_pending_requests(), "Non-empty queue should return True"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from unittest.mock import MagicMock
                from scrapy.core.scheduler import Scheduler
                from scrapy.dupefilters import RFPDupeFilter
                from scrapy.utils.test import get_crawler

                def test_empty_scheduler_has_no_pending():
                    crawler = get_crawler()
                    s = Scheduler(
                        dupefilter=RFPDupeFilter(), jobdir=None,
                        dqclass=None, mqclass=None, logunser=False,
                        stats=MagicMock(), pqclass=None, crawler=crawler,
                    )
                    s.open(MagicMock())
                    assert s.has_pending_requests() == False

                def test_scheduler_queue_reports_pending():
                    from scrapy.http import Request
                    crawler = get_crawler(settings_dict={
                        'SCHEDULER_DEBUG': False,
                        'JOBDIR': None,
                        'DUPEFILTER_CLASS': 'scrapy.dupefilters.BaseDupeFilter',
                    })
                    s = Scheduler(
                        dupefilter=RFPDupeFilter(), jobdir=None,
                        dqclass=None, mqclass=None, logunser=False,
                        stats=MagicMock(), pqclass=None, crawler=crawler,
                    )
                    s.open(MagicMock())
                    assert s.enqueue_request(Request('https://example.com/pending')) is True
                    assert s.has_pending_requests() is True
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Request fingerprint — method not included in hash
    # ------------------------------------------------------------------
    {
        "task_id": "fingerprint_method_excluded",
        "source_file": "scrapy/utils/request.py",
        "family": "request",
        "difficulty": 3,
        "description": "fingerprint() must include HTTP method; regression omits it so GET/POST collide",
        "find": "        fp.update(to_bytes(request.method))\n        fp.update(",
        "replace": "        # BUG: method not included in fingerprint\n        fp.update(",
        "prompt": textwrap.dedent("""\
            `scrapy.utils.request.fingerprint()` must include the HTTP method
            in the hash so that a GET and a POST to the same URL produce
            different fingerprints.  After a recent change the method is no
            longer hashed, causing GET and POST requests to the same URL to
            be incorrectly identified as duplicates.

            Fix `fingerprint()` so the HTTP method is included in the hash.

            Verify with: pytest tests/test_utils_request.py -k fingerprint -q
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import Request
            from scrapy.utils.request import fingerprint

            def test_get_and_post_different_fingerprint():
                get_req = Request('https://example.com/api', method='GET')
                post_req = Request('https://example.com/api', method='POST')
                assert fingerprint(get_req) != fingerprint(post_req), (
                    "GET and POST to same URL must have different fingerprints"
                )

            def test_same_method_same_fingerprint():
                r1 = Request('https://example.com/page', method='GET')
                r2 = Request('https://example.com/page', method='GET')
                assert fingerprint(r1) == fingerprint(r2)
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import Request
                from scrapy.utils.request import fingerprint

                def test_put_delete_different():
                    put = Request('https://x.com/r', method='PUT')
                    delete = Request('https://x.com/r', method='DELETE')
                    assert fingerprint(put) != fingerprint(delete)
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Scheduler enqueue — dont_filter always bypasses dupefilter
    # ------------------------------------------------------------------
    {
        "task_id": "scheduler_dont_filter_inverted",
        "source_file": "scrapy/core/scheduler.py",
        "family": "scheduler",
        "difficulty": 3,
        "description": "dont_filter=True must skip dupefilter; regression inverts the logic",
        "find": "        if not request.dont_filter and self.df.request_seen(request):",
        "replace": "        if request.dont_filter and self.df.request_seen(request):  # BUG: inverted",
        "prompt": textwrap.dedent("""\
            When `request.dont_filter = True`, the scheduler should bypass
            the dupefilter entirely and always enqueue the request.  After a
            recent change the condition was inverted: `dont_filter=True`
            requests are now filtered (dropped) while `dont_filter=False`
            requests always pass through.

            Fix `enqueue_request` so `dont_filter=True` correctly bypasses
            duplicate filtering.

            Verify with: pytest tests/test_scheduler.py -q
        """),
        "visible_test": textwrap.dedent("""\
            from unittest.mock import MagicMock
            from scrapy.http import Request
            from scrapy.core.scheduler import Scheduler
            from scrapy.dupefilters import RFPDupeFilter
            from scrapy.utils.test import get_crawler

            def test_dont_filter_enqueues_duplicate():
                crawler = get_crawler()
                scheduler = Scheduler(
                    dupefilter=RFPDupeFilter(), jobdir=None,
                    dqclass=None, mqclass=None, logunser=False,
                    stats=MagicMock(), pqclass=None, crawler=crawler,
                )
                scheduler.open(MagicMock())
                req1 = Request('https://example.com', dont_filter=False)
                req2 = Request('https://example.com', dont_filter=True)
                result1 = scheduler.enqueue_request(req1)
                result2 = scheduler.enqueue_request(req2)
                assert result1 is True, "First request should be enqueued"
                assert result2 is True, "dont_filter=True should bypass dedup"
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from unittest.mock import MagicMock
                from scrapy.http import Request
                from scrapy.core.scheduler import Scheduler
                from scrapy.dupefilters import RFPDupeFilter
                from scrapy.utils.test import get_crawler

                def test_duplicate_without_dont_filter_is_dropped():
                    crawler = get_crawler()
                    s = Scheduler(
                        dupefilter=RFPDupeFilter(), jobdir=None,
                        dqclass=None, mqclass=None, logunser=False,
                        stats=MagicMock(), pqclass=None, crawler=crawler,
                    )
                    s.open(MagicMock())
                    req = Request('https://example.com', dont_filter=False)
                    assert s.enqueue_request(req) is True
                    assert s.enqueue_request(req) is False  # duplicate dropped
            """),
        ],
    },

    # ------------------------------------------------------------------
    # Response text decoding uses wrong encoding
    # ------------------------------------------------------------------
    {
        "task_id": "response_text_wrong_encoding",
        "source_file": "scrapy/http/response/text.py",
        "family": "response",
        "difficulty": 2,
        "description": "response.text must decode with response encoding; regression uses utf-8",
        "find": "            charset = f\"charset={benc}\"\n            self._cached_ubody = html_to_unicode(charset, self.body)[1]",
        "replace": "            charset = \"charset=utf-8\"  # BUG: ignores response encoding\n            self._cached_ubody = html_to_unicode(charset, self.body)[1]",
        "prompt": textwrap.dedent("""\
            `TextResponse.text` should decode response bodies using the
            response's declared encoding. After a recent change it always
            decodes as UTF-8, which corrupts responses declared with a
            different charset such as Latin-1.

            Fix `TextResponse.text` so it honors the response encoding when
            decoding the body.
        """),
        "visible_test": textwrap.dedent("""\
            from scrapy.http import TextResponse

            def test_text_response_uses_declared_encoding():
                resp = TextResponse(
                    'https://example.com',
                    body='héllo'.encode('latin-1'),
                    encoding='latin-1',
                )
                assert resp.text == 'héllo'
        """),
        "hidden_tests": [
            textwrap.dedent("""\
                from scrapy.http import TextResponse
                def test_text_response_decodes_correctly():
                    resp = TextResponse('https://example.com',
                                        body='héllo'.encode('latin-1'),
                                        encoding='latin-1')
                    assert resp.text == 'héllo'
                def test_text_response_utf8_still_works():
                    resp = TextResponse(
                        'https://example.com',
                        body='snowman ☃'.encode('utf-8'),
                        encoding='utf-8',
                    )
                    assert resp.text == 'snowman ☃'
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
