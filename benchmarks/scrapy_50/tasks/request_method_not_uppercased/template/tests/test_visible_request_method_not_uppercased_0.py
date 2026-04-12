from scrapy.http import Request

def test_lowercase_method_is_uppercased():
    req = Request('https://example.com', method='get')
    assert req.method == 'GET', f"Expected GET, got {req.method!r}"

def test_mixed_case_method_is_uppercased():
    req = Request('https://example.com', method='Post')
    assert req.method == 'POST', f"Expected POST, got {req.method!r}"
