from scrapy.http import Request
from scrapy.downloadermiddlewares.useragent import UserAgentMiddleware
from scrapy.utils.test import get_crawler
from unittest.mock import MagicMock

def test_custom_ua_not_overridden():
    crawler = get_crawler(settings_dict={'USER_AGENT': 'DefaultBot'})
    mw = UserAgentMiddleware.from_crawler(crawler)
    req = Request('https://example.com',
                  headers={'User-Agent': 'CustomBot/1.0'})
    spider = MagicMock()
    mw.process_request(req, spider)
    ua = req.headers.get(b'User-Agent', b'').decode()
    assert 'CustomBot' in ua, (
        f"Custom UA was overwritten. Got: {ua!r}"
    )
