from scrapy.settings import Settings

def test_settings_copy_isolation():
    s = Settings({'FOO': 'bar', 'NUM': 42})
    c = s.copy()
    c.set('FOO', 'mutated')
    assert s['FOO'] == 'bar', f"Original was mutated: {s['FOO']!r}"

def test_settings_copy_preserves_values():
    s = Settings({'KEY': 'value'})
    c = s.copy()
    assert c['KEY'] == 'value'
