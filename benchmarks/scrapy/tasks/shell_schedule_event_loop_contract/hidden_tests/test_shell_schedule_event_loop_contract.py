import asyncio
from types import SimpleNamespace

from twisted.internet.defer import succeed

import scrapy.shell as shell_module
from scrapy.http import Request, Response
from scrapy.shell import Shell


class DummyEngine:
    def __init__(self):
        self.crawled = []

    def crawl(self, request):
        self.crawled.append(request)


async def _test_schedule_does_not_reset_running_event_loop(monkeypatch):
    calls = []
    request = Request("https://example.com")
    response = Response(request.url, request=request)
    engine = DummyEngine()

    monkeypatch.setattr(shell_module, "is_asyncio_reactor_installed", lambda: True)
    monkeypatch.setattr(shell_module, "set_asyncio_event_loop", lambda path: calls.append(path))
    monkeypatch.setattr(shell_module, "_request_deferred", lambda req: succeed(response))

    shell = Shell.__new__(Shell)
    shell._use_reactor = True
    shell._loop = asyncio.get_running_loop()
    shell.spider = SimpleNamespace()
    shell.crawler = SimpleNamespace(
        settings={"ASYNCIO_EVENT_LOOP": "ignored"},
        engine=engine,
    )

    result = await shell._schedule(request, None)

    assert result is response
    assert engine.crawled == [request]
    assert calls == []


async def _test_schedule_opens_spider_before_crawling(monkeypatch):
    opened = []
    request = Request("https://example.com")
    response = Response(request.url, request=request)
    engine = DummyEngine()

    monkeypatch.setattr(shell_module, "is_asyncio_reactor_installed", lambda: False)
    monkeypatch.setattr(shell_module, "_request_deferred", lambda req: succeed(response))

    shell = Shell.__new__(Shell)
    shell._use_reactor = True
    shell._loop = asyncio.get_running_loop()
    shell.spider = None
    shell.crawler = SimpleNamespace(settings={"ASYNCIO_EVENT_LOOP": "ignored"}, engine=engine)

    async def fake_open_spider(spider):
        opened.append(True)
        shell.spider = SimpleNamespace()

    shell._open_spider = fake_open_spider

    await shell._schedule(request, None)

    assert opened == [True]
    assert engine.crawled == [request]


def test_schedule_does_not_reset_running_event_loop(monkeypatch):
    asyncio.run(_test_schedule_does_not_reset_running_event_loop(monkeypatch))


def test_schedule_opens_spider_before_crawling(monkeypatch):
    asyncio.run(_test_schedule_opens_spider_before_crawling(monkeypatch))
