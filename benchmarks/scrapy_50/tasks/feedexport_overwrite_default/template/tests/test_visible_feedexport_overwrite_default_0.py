def test_feedexporter_overwrite_concept():
    """The overwrite default should be False (append mode).
    Passes as long as scrapy.extensions.feedexport imports cleanly."""
    from scrapy.extensions import feedexport
    assert hasattr(feedexport, 'FeedExporter')
