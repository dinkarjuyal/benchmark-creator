import asyncio
from types import SimpleNamespace

from scrapy import Request
from scrapy.downloadermiddlewares.httpcache import HttpCacheMiddleware
from scrapy.http import Response


class DummyPolicy:
    def should_cache_request(self, request):
        return True

    def is_cached_response_fresh(self, cachedresponse, request):
        return True

    def is_cached_response_valid(self, cachedresponse, response, request):
        return True

    def should_cache_response(self, response, request):
        return True


class DummyStats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key):
        self.values[key] = self.values.get(key, 0) + 1


class AsyncStorage:
    def __init__(self):
        self.stored = []

    async def retrieve_response(self, spider, request):
        await asyncio.sleep(0)
        return Response(request.url, body=b"cached")

    async def store_response(self, spider, request, response):
        await asyncio.sleep(0)
        self.stored.append((request.url, response.body))


class SyncStorage:
    def retrieve_response(self, spider, request):
        return Response(request.url, body=b"sync")

    def store_response(self, spider, request, response):
        return None


def _make_middleware(storage):
    mw = HttpCacheMiddleware.__new__(HttpCacheMiddleware)
    mw.policy = DummyPolicy()
    mw.storage = storage
    mw.ignore_missing = False
    mw.stats = DummyStats()
    mw.crawler = SimpleNamespace(spider=SimpleNamespace())
    return mw


async def _test_async_cache_retrieval_is_awaited():
    mw = _make_middleware(AsyncStorage())
    request = Request("https://example.com")

    response = await mw.process_request_async(request)

    assert isinstance(response, Response)
    assert response.body == b"cached"
    assert "cached" in response.flags


async def _test_sync_cache_retrieval_still_works():
    mw = _make_middleware(SyncStorage())
    request = Request("https://example.com")

    response = await mw.process_request_async(request)

    assert isinstance(response, Response)
    assert response.body == b"sync"


async def _test_async_cache_store_completes_before_return():
    storage = AsyncStorage()
    mw = _make_middleware(storage)
    request = Request("https://example.com")
    response = Response(request.url, body=b"payload")

    returned = await mw.process_response_async(request, response)

    assert returned is response
    assert storage.stored == [("https://example.com", b"payload")]


def test_async_cache_retrieval_is_awaited():
    asyncio.run(_test_async_cache_retrieval_is_awaited())


def test_sync_cache_retrieval_still_works():
    asyncio.run(_test_sync_cache_retrieval_still_works())


def test_async_cache_store_completes_before_return():
    asyncio.run(_test_async_cache_store_completes_before_return())
