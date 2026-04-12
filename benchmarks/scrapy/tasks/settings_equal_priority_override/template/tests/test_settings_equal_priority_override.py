from scrapy.settings import BaseSettings


def test_equal_priority_update_replaces_previous_value():
    settings = BaseSettings({"DOWNLOAD_DELAY": "0.25"}, priority="project")

    settings.set("DOWNLOAD_DELAY", "0.5", priority="project")

    assert settings["DOWNLOAD_DELAY"] == "0.5"
    assert settings.getpriority("DOWNLOAD_DELAY") == 20


def test_lower_priority_update_still_does_not_replace_existing_value():
    settings = BaseSettings({"DOWNLOAD_DELAY": "0.25"}, priority="project")

    settings.set("DOWNLOAD_DELAY", "1.0", priority="default")

    assert settings["DOWNLOAD_DELAY"] == "0.25"
