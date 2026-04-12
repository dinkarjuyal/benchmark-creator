from scrapy.settings import Settings

def test_getlist_with_default():
    s = Settings()
    result = s.getlist('NONEXISTENT_SETTING_XYZ', default=['x', 'y'])
    assert result == ['x', 'y'], f"Expected ['x', 'y'], got {result!r}"

def test_getlist_default_empty_list():
    s = Settings()
    result = s.getlist('NONEXISTENT_SETTING_XYZ', default=[])
    assert result == [], f"Expected [], got {result!r}"
