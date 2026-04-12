import asyncio
import warnings
from collections import deque

from twisted.internet.defer import succeed

from scrapy import Request
from scrapy.core.downloader.middleware import DownloaderMiddlewareManager
from scrapy.exceptions import ScrapyDeprecationWarning
from scrapy.http import Response


class DeferredRequestMiddleware:
    def process_request(self, request):
        return succeed(Response(request.url, body=b"deferred"))


class SyncRequestMiddleware:
    def process_request(self, request):
        return Response(request.url, body=b"sync")


class OrderTrackingMiddleware:
    def __init__(self, events):
        self.events = events

    def process_response(self, request, response):
        self.events.append(response.body.decode())
        return Response(request.url, body=response.body + b":wrapped")


def _manager(*middlewares):
    manager = DownloaderMiddlewareManager(*middlewares)
    manager.methods["process_request"] = deque()
    manager.methods["process_response"] = deque()
    manager.methods["process_exception"] = deque()
    for mw in middlewares:
        manager._add_middleware(mw)
    return manager


async def _test_download_async_accepts_deferred_from_process_request():
    manager = _manager(DeferredRequestMiddleware())
    request = Request("https://example.com")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        response = await manager.download_async(
            lambda req: succeed(Response(req.url, body=b"downloaded")), request
        )

    assert isinstance(response, Response)
    assert response.body == b"deferred"
    assert any(issubclass(w.category, ScrapyDeprecationWarning) for w in caught)


async def _test_download_async_preserves_sync_middleware_behavior():
    manager = _manager(SyncRequestMiddleware())
    request = Request("https://example.com")

    response = await manager.download_async(
        lambda req: succeed(Response(req.url, body=b"downloaded")), request
    )

    assert isinstance(response, Response)
    assert response.body == b"sync"


async def _test_download_async_preserves_process_response_ordering():
    events = []
    manager = _manager(OrderTrackingMiddleware(events))
    request = Request("https://example.com")

    response = await manager.download_async(
        lambda req: succeed(Response(req.url, body=b"downloaded")), request
    )

    assert response.body == b"downloaded:wrapped"
    assert events == ["downloaded"]


def test_download_async_accepts_deferred_from_process_request():
    asyncio.run(_test_download_async_accepts_deferred_from_process_request())


def test_download_async_preserves_sync_middleware_behavior():
    asyncio.run(_test_download_async_preserves_sync_middleware_behavior())


def test_download_async_preserves_process_response_ordering():
    asyncio.run(_test_download_async_preserves_process_response_ordering())
