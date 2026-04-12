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
