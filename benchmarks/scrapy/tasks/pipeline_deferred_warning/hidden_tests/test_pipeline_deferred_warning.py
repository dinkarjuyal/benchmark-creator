import asyncio

from types import SimpleNamespace

import pytest
from twisted.internet.defer import succeed

from scrapy.exceptions import ScrapyDeprecationWarning
from scrapy.pipelines import ItemPipelineManager
from scrapy.utils.test import get_crawler


class DeferredPipeline:
    def process_item(self, item, spider):
        return succeed(item)


class SyncPipeline:
    def process_item(self, item, spider):
        return item


def _make_manager(pipeline_cls):
    crawler = get_crawler(
        settings_dict={"ITEM_PIPELINES": {f"{__name__}.{pipeline_cls.__name__}": 100}}
    )
    manager = ItemPipelineManager.from_crawler(crawler)
    manager._set_compat_spider(SimpleNamespace())
    return manager


async def _test_deferred_pipeline_emits_warning():
    manager = _make_manager(DeferredPipeline)

    with pytest.warns(ScrapyDeprecationWarning, match="returned a Deferred"):
        item = await manager.process_item_async({"value": 1})

    assert item == {"value": 1}


async def _test_sync_pipeline_still_returns_item_without_warning():
    manager = _make_manager(SyncPipeline)

    with pytest.warns(None) as record:
        item = await manager.process_item_async({"value": 2})

    assert item == {"value": 2}
    assert not record


def test_deferred_pipeline_emits_warning():
    asyncio.run(_test_deferred_pipeline_emits_warning())


def test_sync_pipeline_still_returns_item_without_warning():
    asyncio.run(_test_sync_pipeline_still_returns_item_without_warning())
