from scrapy.settings import Settings

def test_same_priority_replaces_noop_check():
    s = Settings()
    s.set('FOO', 'first', priority='default')
    s.set('FOO', 'second', priority='default')
    assert s['FOO'] == 'second'

def test_lower_priority_ignored_noop_check():
    s = Settings()
    s.set('BAR', 'high', priority='spider')
    s.set('BAR', 'low', priority='default')
    assert s['BAR'] == 'high'
