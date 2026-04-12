import pytest

from scrapy.pipelines import ItemPipelineManager
from scrapy.utils.test import get_crawler


class GoodPipeline:
    @classmethod
    def from_crawler(cls, crawler):
        return cls()

    def process_item(self, item, spider):
        return item


class BrokenPipeline:
    @classmethod
    def from_crawler(cls, crawler):
        raise RuntimeError("broken pipeline setup")


class NonePipeline:
    @classmethod
    def from_crawler(cls, crawler):
        return None


def _make_crawler(pipeline_cls):
    return get_crawler(
        settings_dict={
            "ITEM_PIPELINES": {f"{__name__}.{pipeline_cls.__name__}": 100},
        }
    )


def test_pipeline_setup_error_is_not_suppressed():
    crawler = _make_crawler(BrokenPipeline)
    with pytest.raises(RuntimeError, match="broken pipeline setup"):
        ItemPipelineManager.from_crawler(crawler)


def test_valid_pipeline_still_loads():
    crawler = _make_crawler(GoodPipeline)
    manager = ItemPipelineManager.from_crawler(crawler)
    assert len(manager.middlewares) == 1
    assert isinstance(manager.middlewares[0], GoodPipeline)


def test_none_return_from_from_crawler_still_raises_type_error():
    crawler = _make_crawler(NonePipeline)
    with pytest.raises(TypeError, match="returned None"):
        ItemPipelineManager.from_crawler(crawler)
