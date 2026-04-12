from scrapy.dupefilters import RFPDupeFilter
from scrapy.http import Request

def test_fingerprint_stored_after_first_seen():
    df = RFPDupeFilter()
    req = Request('https://example.com')
    assert df.request_seen(req) is False   # first time: new
    assert df.request_seen(req) is True    # second time: duplicate
