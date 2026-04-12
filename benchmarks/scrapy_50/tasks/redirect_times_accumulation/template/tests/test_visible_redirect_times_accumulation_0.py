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
