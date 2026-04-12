import pytest
from scrapy.exceptions import NotConfigured
from scrapy.downloadermiddlewares.httpcache import HttpCacheMiddleware
from scrapy.utils.test import get_crawler

def test_disabled_raises_not_configured():
    crawler = get_crawler(settings_dict={'HTTPCACHE_ENABLED': False})
    with pytest.raises(NotConfigured):
        HttpCacheMiddleware.from_crawler(crawler)

def test_enabled_does_not_raise():
    crawler = get_crawler(settings_dict={
        'HTTPCACHE_ENABLED': True,
        'HTTPCACHE_DIR': '/tmp/test_cache'
    })
    mw = HttpCacheMiddleware.from_crawler(crawler)
    assert mw is not None
