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
