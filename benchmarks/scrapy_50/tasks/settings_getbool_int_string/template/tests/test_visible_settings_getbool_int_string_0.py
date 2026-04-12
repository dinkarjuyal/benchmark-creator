from scrapy.settings import Settings
def test_getbool_string_zero_is_false():
    s = Settings({'FLAG': '0'})
    assert s.getbool('FLAG') is False, f"'0' should be False, got {s.getbool('FLAG')!r}"
def test_getbool_string_one_is_true():
    s = Settings({'FLAG': '1'})
    assert s.getbool('FLAG') is True
