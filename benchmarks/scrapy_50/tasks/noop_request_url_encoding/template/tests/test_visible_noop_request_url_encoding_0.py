from scrapy.http import Request

def test_url_encoding_spaces():
    req = Request('https://example.com/search?q=hello%20world')
    assert 'hello%20world' in req.url

def test_url_already_encoded():
    req = Request('https://example.com/path%2Fwith%2Fslashes')
    assert req.url == 'https://example.com/path%2Fwith%2Fslashes'
