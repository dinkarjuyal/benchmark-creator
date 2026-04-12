from scrapy.settings import Settings

def test_user_value_overrides_base():
    s = Settings()
    s.set('MY_BASE', {'a': 1, 'b': 2})
    s.set('MY', {'b': 99})
    merged = s.getwithbase('MY')
    assert merged['b'] == 99, (
        f"User value should override base, got {merged['b']}"
    )
    assert merged['a'] == 1, "Base-only entry should be present"
