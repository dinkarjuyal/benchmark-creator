from scrapy.http import Request

def test_replace_preserves_headers():
    req = Request('https://example.com',
                  headers={'X-Custom': 'yes'},
                  method='POST')
    new = req.replace(url='https://other.com')
    assert new.method == 'POST', f"Method not preserved: {new.method!r}"

def test_replace_overrides_specified():
    req = Request('https://example.com', method='GET')
    new = req.replace(method='POST')
    assert new.method == 'POST'
    assert new.url == 'https://example.com'
