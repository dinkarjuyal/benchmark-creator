from types import SimpleNamespace

from scrapy.extensions.throttle import AutoThrottle
from scrapy.utils.test import get_crawler as _get_crawler


def get_crawler(settings=None):
    settings = settings or {}
    settings["AUTOTHROTTLE_ENABLED"] = True
    return _get_crawler(settings_dict=settings)


def test_spider_opened_preserves_explicit_download_delay():
    crawler = get_crawler({"AUTOTHROTTLE_START_DELAY": 5.0, "DOWNLOAD_DELAY": 0.25})
    at = AutoThrottle.from_crawler(crawler)
    spider = SimpleNamespace(download_delay=3.0)

    at._spider_opened(spider)

    assert spider.download_delay == 3.0


def test_spider_opened_does_not_create_download_delay_attribute():
    crawler = get_crawler({"AUTOTHROTTLE_START_DELAY": 5.0, "DOWNLOAD_DELAY": 0.25})
    at = AutoThrottle.from_crawler(crawler)
    spider = SimpleNamespace()

    at._spider_opened(spider)

    assert not hasattr(spider, "download_delay")
