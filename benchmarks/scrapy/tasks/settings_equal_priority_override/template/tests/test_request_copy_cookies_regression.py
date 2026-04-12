from scrapy import Request


def test_copy_keeps_dict_cookies_independent():
    original = Request("https://example.org", cookies={"session": "abc"})

    cloned = original.copy()
    cloned.cookies["token"] = "xyz"

    assert original.cookies == {"session": "abc"}
    assert cloned.cookies == {"session": "abc", "token": "xyz"}


def test_replace_keeps_verbose_cookie_lists_independent():
    original = Request(
        "https://example.org",
        cookies=[{"name": "session", "value": "abc"}],
    )

    replaced = original.replace()
    replaced.cookies.append({"name": "token", "value": "xyz"})

    assert original.cookies == [{"name": "session", "value": "abc"}]
    assert replaced.cookies == [
        {"name": "session", "value": "abc"},
        {"name": "token", "value": "xyz"},
    ]
