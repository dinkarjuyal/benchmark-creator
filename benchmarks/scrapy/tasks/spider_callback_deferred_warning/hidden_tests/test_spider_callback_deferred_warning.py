import asyncio

import pytest
from twisted.internet.defer import succeed
from twisted.python.failure import Failure

from scrapy import Request, Spider
from scrapy.core.scraper import Scraper
from scrapy.exceptions import ScrapyDeprecationWarning
from scrapy.http import Response
from scrapy.utils.test import get_crawler


class DeferredSpider(Spider):
    name = "deferred-spider"

    def parse(self, response):
        return succeed([{"ok": 1}])

    def on_error(self, failure):
        return succeed([{"error": True}])


async def _test_deferred_callback_emits_warning():
    crawler = get_crawler(DeferredSpider, settings_dict={"LOG_ENABLED": False})
    spider = DeferredSpider()
    crawler.spider = spider
    scraper = Scraper(crawler)
    request = Request("https://example.com", callback=spider.parse)
    response = Response(request.url, request=request)

    with pytest.warns(
        ScrapyDeprecationWarning,
        match="Returning Deferreds from spider callbacks is deprecated",
    ):
        output = await scraper.call_spider_async(response, request)

    assert list(output) == [{"ok": 1}]


async def _test_deferred_errback_emits_warning():
    crawler = get_crawler(DeferredSpider, settings_dict={"LOG_ENABLED": False})
    spider = DeferredSpider()
    crawler.spider = spider
    scraper = Scraper(crawler)
    request = Request("https://example.com", errback=spider.on_error)
    failure = Failure(RuntimeError("boom"))

    with pytest.warns(
        ScrapyDeprecationWarning,
        match="Returning Deferreds from spider errbacks is deprecated",
    ):
        output = await scraper.call_spider_async(failure, request)

    assert list(output) == [{"error": True}]


def test_deferred_callback_emits_warning():
    asyncio.run(_test_deferred_callback_emits_warning())


def test_deferred_errback_emits_warning():
    asyncio.run(_test_deferred_errback_emits_warning())
