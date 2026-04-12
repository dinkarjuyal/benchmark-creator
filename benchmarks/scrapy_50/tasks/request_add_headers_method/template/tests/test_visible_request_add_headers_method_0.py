from scrapy.http import Request

def test_with_headers_merges():
    req = Request('https://example.com', headers={'User-Agent': 'bot'})
    new = req.with_headers({'Authorization': 'Bearer token'})
    assert b'Authorization' in new.headers or 'Authorization' in new.headers
    assert new.url == req.url

def test_with_headers_original_unchanged():
    req = Request('https://example.com', headers={'A': '1'})
    _ = req.with_headers({'B': '2'})
    assert b'B' not in req.headers and 'B' not in req.headers
