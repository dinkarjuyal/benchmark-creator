from scrapy.spiders import Spider

def test_spider_has_name():
    class MySpider(Spider):
        name = 'my_spider'
    s = MySpider()
    assert s.name == 'my_spider'
