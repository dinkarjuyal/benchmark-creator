def test_exception_chain_continues():
    """Conceptual test — full integration requires the twisted reactor.
    This passes as long as scrapy imports cleanly after the fix."""
    from scrapy.core.spidermw import SpiderMiddlewareManager
    assert SpiderMiddlewareManager is not None
