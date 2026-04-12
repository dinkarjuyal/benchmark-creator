from scrapy.dupefilters import RFPDupeFilter
from scrapy.http import Request

def test_clear_resets_seen():
    df = RFPDupeFilter()
    req = Request('https://example.com')
    df.request_seen(req)   # mark as seen
    df.clear()             # reset
    assert df.request_seen(req) is False, (
        "After clear(), the URL should appear new again"
    )
