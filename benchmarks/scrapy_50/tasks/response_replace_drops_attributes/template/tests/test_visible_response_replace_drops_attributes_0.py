from scrapy.http import Response

def test_replace_preserves_body():
    resp = Response('https://example.com', body=b'hello', status=200)
    new = resp.replace(status=404)
    assert new.body == b'hello', f"Body not preserved: {new.body!r}"
    assert new.status == 404
    assert new.url == 'https://example.com'

def test_replace_preserves_headers():
    resp = Response('https://example.com',
                    headers={'Content-Type': 'text/html'}, status=200)
    new = resp.replace(status=301)
    assert new.headers.get('Content-Type') == b'text/html'
