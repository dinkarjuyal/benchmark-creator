from __future__ import annotations

import asyncio

import scrapy
from scrapy import signals
from scrapy.utils.test import get_crawler

from start_pipeline_helpers import TrackingPipeline


class StartItemSpider(scrapy.Spider):
    name = "start-item-spider"

    async def start(self):
        yield {"source": "start"}


async def _start_crawl():
    TrackingPipeline.reset()
    scraped_items: list[dict] = []
    def on_item_scraped(item, response, spider):
        scraped_items.append(item)

    crawler = get_crawler(
        StartItemSpider,
        {
            "ITEM_PIPELINES": {"start_pipeline_helpers.TrackingPipeline": 100},
            "LOG_ENABLED": False,
            "TWISTED_REACTOR_ENABLED": False,
        },
    )
    crawler.signals.connect(on_item_scraped, signal=signals.item_scraped, weak=False)
    crawl_task = asyncio.create_task(crawler.crawl_async())
    await asyncio.wait_for(TrackingPipeline.started.wait(), timeout=2)
    return crawl_task, scraped_items


def test_crawl_waits_for_start_item_pipeline_completion():
    async def scenario():
        crawl_task, _ = await _start_crawl()
        await asyncio.sleep(0.2)
        assert not crawl_task.done()
        TrackingPipeline.release.set()
        await asyncio.wait_for(crawl_task, timeout=2)

    asyncio.run(scenario())


def test_item_is_scraped_after_pipeline_release():
    async def scenario():
        crawl_task, scraped_items = await _start_crawl()
        assert scraped_items == []
        TrackingPipeline.release.set()
        await asyncio.wait_for(crawl_task, timeout=2)
        assert TrackingPipeline.finished.is_set()
        assert TrackingPipeline.processed_items == [{"source": "start"}]
        assert scraped_items == [{"source": "start"}]

    asyncio.run(scenario())
