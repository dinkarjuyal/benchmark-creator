import scrapy

class MySpider(scrapy.Spider):
    name = 'my_spider'
    start_urls = []

def test_logger_named_after_spider_name():
    spider = MySpider.from_settings(scrapy.settings.Settings())
    assert spider.logger.logger.name == 'my_spider', (
        f"Logger name should be spider.name, got {spider.logger.logger.name!r}"
    )
