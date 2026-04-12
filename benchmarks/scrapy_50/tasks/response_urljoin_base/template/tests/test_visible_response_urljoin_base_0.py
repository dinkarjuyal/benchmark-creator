from scrapy.http import Response
def test_urljoin_relative_path():
    r = Response('https://example.com/foo/bar')
    assert r.urljoin('/baz') == 'https://example.com/baz'
def test_urljoin_relative_file():
    r = Response('https://example.com/foo/bar')
    result = r.urljoin('other')
    assert result == 'https://example.com/foo/other', f"Got: {result}"
