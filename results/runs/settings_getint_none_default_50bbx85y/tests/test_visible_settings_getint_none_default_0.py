from scrapy.settings import Settings
def test_getint_none_default_returns_none():
    s = Settings()
    result = s.getint('NONEXISTENT_KEY_XYZ', default=None)
    assert result is None, f"Expected None, got {result!r}"
