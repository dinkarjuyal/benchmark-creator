from scrapy.settings import Settings

def test_same_priority_replaces():
    s = Settings()
    s.set('FOO', 'first', priority='default')
    s.set('FOO', 'second', priority='default')
    assert s['FOO'] == 'second', f"Expected 'second', got {s['FOO']!r}"
