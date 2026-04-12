import pytest
from scrapy.exceptions import NotConfigured
from scrapy.downloadermiddlewares.cookies import CookiesMiddleware
from scrapy.utils.test import get_crawler

def test_cookies_disabled_raises_not_configured():
    crawler = get_crawler(settings_dict={'COOKIES_ENABLED': False})
    with pytest.raises(NotConfigured):
        CookiesMiddleware.from_crawler(crawler)
