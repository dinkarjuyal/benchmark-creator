import pytest
from scrapy.exceptions import NotConfigured
from scrapy.downloadermiddlewares.httpcompression import HttpCompressionMiddleware
from scrapy.utils.test import get_crawler

def test_compression_disabled_raises():
    crawler = get_crawler(settings_dict={'COMPRESSION_ENABLED': False})
    with pytest.raises(NotConfigured):
        HttpCompressionMiddleware.from_crawler(crawler)
