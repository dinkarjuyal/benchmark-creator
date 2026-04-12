from scrapy.http import Request
from scrapy.utils.request import fingerprint

def test_fingerprint_with_include_headers_differs():
    r1 = Request('https://example.com', headers={'Auth': 'token-A'})
    r2 = Request('https://example.com', headers={'Auth': 'token-B'})
    fp1 = fingerprint(r1, include_headers=['Auth'])
    fp2 = fingerprint(r2, include_headers=['Auth'])
    assert fp1 != fp2, "Different Auth headers should yield different fingerprints"

def test_fingerprint_default_ignores_headers():
    r1 = Request('https://example.com', headers={'Auth': 'token-A'})
    r2 = Request('https://example.com', headers={'Auth': 'token-B'})
    assert fingerprint(r1) == fingerprint(r2), (
        "Without include_headers, fingerprints should match"
    )
