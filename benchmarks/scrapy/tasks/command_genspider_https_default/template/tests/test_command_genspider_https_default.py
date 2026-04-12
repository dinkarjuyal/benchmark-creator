from scrapy.commands.genspider import verify_url_scheme


def test_verify_url_scheme_defaults_bare_domains_to_https():
    assert verify_url_scheme("example.com") == "https://example.com"


def test_verify_url_scheme_preserves_explicit_scheme():
    assert verify_url_scheme("http://example.com") == "http://example.com"
    assert verify_url_scheme("https://example.com/path") == "https://example.com/path"
