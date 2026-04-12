import pytest
from scrapy.http import Request

def test_url_immutable_after_construction():
    req = Request('https://example.com')
    with pytest.raises(AttributeError):
        req.url = 'https://other.com'
