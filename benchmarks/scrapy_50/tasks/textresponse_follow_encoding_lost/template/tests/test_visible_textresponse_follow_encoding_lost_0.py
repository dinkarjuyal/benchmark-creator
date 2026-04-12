from scrapy.http.response.text import TextResponse

def test_follow_relative_url_resolved():
    resp = TextResponse(
        url='https://example.com/section/',
        body=b'<a href="page.html">link</a>',
        encoding='utf-8',
    )
    req = resp.follow('page.html')
    assert req.url == 'https://example.com/section/page.html', (
        f"Unexpected URL: {req.url!r}"
    )

def test_follow_absolute_url_unchanged():
    resp = TextResponse(
        url='https://example.com/',
        body=b'',
        encoding='utf-8',
    )
    req = resp.follow('https://other.com/page')
    assert req.url == 'https://other.com/page'
