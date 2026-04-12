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
