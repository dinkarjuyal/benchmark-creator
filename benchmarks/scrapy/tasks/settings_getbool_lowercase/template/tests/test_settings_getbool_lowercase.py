import pytest

from scrapy.settings import BaseSettings


def test_getbool_accepts_lowercase_true_and_false():
    settings = BaseSettings({"COOKIES_ENABLED": "true", "COOKIES_DEBUG": "false"})

    assert settings.getbool("COOKIES_ENABLED") is True
    assert settings.getbool("COOKIES_DEBUG") is False


def test_getbool_still_rejects_invalid_strings():
    settings = BaseSettings({"COOKIES_ENABLED": "sometimes"})

    with pytest.raises(ValueError):
        settings.getbool("COOKIES_ENABLED")
