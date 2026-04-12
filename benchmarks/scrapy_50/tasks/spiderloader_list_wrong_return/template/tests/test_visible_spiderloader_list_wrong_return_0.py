import sys
import types
from scrapy.spiderloader import SpiderLoader
from scrapy.spiders import Spider
from scrapy.utils.test import get_crawler

class MySpider(Spider):
    name = 'myspider'

def test_list_returns_spider_names(tmp_path, monkeypatch):
    mod = types.ModuleType('mymod')
    mod.MySpider = MySpider
    monkeypatch.setitem(sys.modules, 'mymod', mod)
    crawler = get_crawler(settings_dict={'SPIDER_MODULES': ['mymod']})
    loader = SpiderLoader.from_crawler(crawler)
    names = loader.list()
    assert 'myspider' in names, f"Expected 'myspider' in {names}"
