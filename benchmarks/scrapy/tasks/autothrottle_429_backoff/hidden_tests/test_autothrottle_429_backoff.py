from unittest.mock import Mock

from scrapy import Request
from scrapy.extensions.throttle import AutoThrottle
from scrapy.http.response import Response
from scrapy.utils.test import get_crawler as _get_crawler


def get_crawler(settings=None):
    settings = settings or {}
    settings["AUTOTHROTTLE_ENABLED"] = True
    return _get_crawler(settings_dict=settings)


def make_slot(delay):
    slot = Mock()
    slot.delay = delay
    slot.transferring = ()
    return slot


def configure_autothrottle(settings=None):
    crawler = get_crawler(settings)
    at = AutoThrottle.from_crawler(crawler)
    spider = Mock()
    spider.download_delay = settings.get("DOWNLOAD_DELAY", 0.0) if settings else 0.0
    at._spider_opened(spider)
    crawler.engine = Mock()
    crawler.engine.downloader = Mock()
    crawler.engine.downloader.slots = {}
    return crawler, at


def test_non_429_responses_keep_existing_behavior():
    crawler, at = configure_autothrottle({"AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0})
    slot = make_slot(1.0)
    crawler.engine.downloader.slots["foo"] = slot
    request = Request("https://example.com", meta={"download_latency": 1.0, "download_slot": "foo"})
    response = Response(request.url, status=200)

    at._response_downloaded(response, request, Mock())

    assert slot.delay == 0.75


def test_429_without_retry_after_doubles_delay():
    crawler, at = configure_autothrottle(
        {
            "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
            "AUTOTHROTTLE_MAX_DELAY": 60.0,
            "DOWNLOAD_DELAY": 0.0,
        }
    )
    slot = make_slot(1.0)
    crawler.engine.downloader.slots["foo"] = slot
    request = Request("https://example.com", meta={"download_latency": 0.5, "download_slot": "foo"})
    response = Response(request.url, status=429)

    at._response_downloaded(response, request, Mock())

    assert slot.delay == 2.0


def test_429_retry_after_sets_minimum_delay():
    crawler, at = configure_autothrottle(
        {
            "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
            "AUTOTHROTTLE_MAX_DELAY": 60.0,
            "DOWNLOAD_DELAY": 0.0,
        }
    )
    slot = make_slot(1.0)
    crawler.engine.downloader.slots["foo"] = slot
    request = Request("https://example.com", meta={"download_latency": 0.5, "download_slot": "foo"})
    response = Response(request.url, status=429, headers={"Retry-After": "15"})

    at._response_downloaded(response, request, Mock())

    assert slot.delay == 15.0


def test_429_retry_after_respects_max_delay():
    crawler, at = configure_autothrottle(
        {
            "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
            "AUTOTHROTTLE_MAX_DELAY": 10.0,
            "DOWNLOAD_DELAY": 0.0,
        }
    )
    slot = make_slot(1.0)
    crawler.engine.downloader.slots["foo"] = slot
    request = Request("https://example.com", meta={"download_latency": 0.5, "download_slot": "foo"})
    response = Response(request.url, status=429, headers={"Retry-After": "30"})

    at._response_downloaded(response, request, Mock())

    assert slot.delay == 10.0


def test_other_error_responses_keep_old_guardrail():
    crawler, at = configure_autothrottle({"AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0})
    slot = make_slot(1.0)
    crawler.engine.downloader.slots["foo"] = slot
    request = Request("https://example.com", meta={"download_latency": 0.5, "download_slot": "foo"})
    response = Response(request.url, status=400)

    at._response_downloaded(response, request, Mock())

    assert slot.delay == 1.0
