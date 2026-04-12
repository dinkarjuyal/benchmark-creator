from scrapy.http import Request
from scrapy.utils.request import fingerprint

def test_get_and_post_different_fingerprint():
    get_req = Request('https://example.com/api', method='GET')
    post_req = Request('https://example.com/api', method='POST')
    assert fingerprint(get_req) != fingerprint(post_req), (
        "GET and POST to same URL must have different fingerprints"
    )

def test_same_method_same_fingerprint():
    r1 = Request('https://example.com/page', method='GET')
    r2 = Request('https://example.com/page', method='GET')
    assert fingerprint(r1) == fingerprint(r2)
