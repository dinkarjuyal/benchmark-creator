import pytest
from unittest.mock import MagicMock, patch
from scrapy.exceptions import IgnoreRequest
from scrapy.http import Request
from scrapy.downloadermiddlewares.robotstxt import RobotsTxtMiddleware
from scrapy.utils.test import get_crawler

def test_disallowed_raises_ignore():
    rp = MagicMock()
    rp.allowed.return_value = False
    crawler = get_crawler(settings_dict={'ROBOTSTXT_OBEY': True})
    mw = RobotsTxtMiddleware.from_crawler(crawler)
    mw._default_useragent = b'Scrapy'
    req = Request('https://example.com/disallowed')
    req.meta['robotstxt_rule'] = None
    with pytest.raises(IgnoreRequest):
        mw.process_request_2(rp, req, MagicMock())

def test_allowed_passes_through():
    rp = MagicMock()
    rp.allowed.return_value = True
    crawler = get_crawler(settings_dict={'ROBOTSTXT_OBEY': True})
    mw = RobotsTxtMiddleware.from_crawler(crawler)
    mw._default_useragent = b'Scrapy'
    req = Request('https://example.com/allowed')
    result = mw.process_request_2(rp, req, MagicMock())
    assert result is None, "Allowed request should pass (return None)"
