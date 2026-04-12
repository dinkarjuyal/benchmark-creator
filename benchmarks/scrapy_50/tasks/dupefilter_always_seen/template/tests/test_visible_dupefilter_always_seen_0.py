from scrapy.dupefilters import RFPDupeFilter
from scrapy.http import Request

def test_first_request_not_seen():
    df = RFPDupeFilter()
    req = Request('https://example.com/page')
    assert df.request_seen(req) is False, "First time must return False"

def test_duplicate_request_is_seen():
    df = RFPDupeFilter()
    req = Request('https://example.com/page')
    df.request_seen(req)
    assert df.request_seen(req) is True, "Second time must return True"
