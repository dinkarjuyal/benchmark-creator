import asyncio

import scrapy.utils.asyncio as scrapy_asyncio


async def _test_parallel_asyncio_uses_queue_size_equal_to_count(monkeypatch):
    seen = {}
    processed = []
    original_queue = asyncio.Queue

    class RecordingQueue(original_queue):
        def __init__(self, maxsize=0):
            seen["maxsize"] = maxsize
            super().__init__(maxsize=maxsize)

    monkeypatch.setattr(scrapy_asyncio.asyncio, "Queue", RecordingQueue)

    async def worker(item):
        processed.append(item)

    await scrapy_asyncio._parallel_asyncio([1, 2, 3], 3, worker)

    assert seen["maxsize"] == 3
    assert processed == [1, 2, 3]


def test_parallel_asyncio_uses_queue_size_equal_to_count(monkeypatch):
    asyncio.run(_test_parallel_asyncio_uses_queue_size_equal_to_count(monkeypatch))
