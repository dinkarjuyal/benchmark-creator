from scrapy.http import Request

def test_meta_isolated_from_caller():
    original_meta = {'key': 'original'}
    req = Request('https://example.com', meta=original_meta)
    original_meta['key'] = 'mutated_by_caller'
    assert req.meta['key'] == 'original', (
        f"Request meta was mutated by external change: {req.meta['key']!r}"
    )
