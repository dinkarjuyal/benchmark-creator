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
