from scrapy.http import Request

def test_cb_kwargs_isolated_from_caller():
    original = {'page': 1}
    req = Request('https://example.com', cb_kwargs=original)
    original['page'] = 999
    assert req.cb_kwargs['page'] == 1, (
        f"cb_kwargs mutated by external change: {req.cb_kwargs['page']!r}"
    )
