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
