def test_short_circuit_concept():
    """
    This is a contract extension task.  The agent must add the sentinel
    constant and wire up the short-circuit logic in the middleware manager.

    A passing visible test just imports scrapy without error after the change.
    """
    import scrapy
    assert hasattr(scrapy, '__version__')
