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
