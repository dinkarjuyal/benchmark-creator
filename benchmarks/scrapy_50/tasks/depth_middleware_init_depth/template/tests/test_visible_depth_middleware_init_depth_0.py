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
