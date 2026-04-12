from scrapy.http import TextResponse

def test_text_response_uses_declared_encoding():
    resp = TextResponse(
        'https://example.com',
        body='héllo'.encode('latin-1'),
        encoding='latin-1',
    )
    assert resp.text == 'héllo'
