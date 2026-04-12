#!/usr/bin/env python3
"""Apply start-state patches to the workspace."""
from pathlib import Path

WORK = Path('/work')

# Patch: scrapy/downloadermiddlewares/useragent.py
_content_scrapy_downloadermiddlewares_useragent_py = '"""Set User-Agent header per spider or use a default value from settings"""\n\nfrom scrapy import signals\n\n\nclass UserAgentMiddleware:\n    """This middleware allows spiders to override the user_agent"""\n\n    def __init__(self, user_agent="Scrapy"):\n        self.user_agent = user_agent\n\n    @classmethod\n    def from_crawler(cls, crawler):\n        o = cls(crawler.settings["USER_AGENT"])\n        crawler.signals.connect(o.spider_opened, signal=signals.spider_opened)\n        return o\n\n    def spider_opened(self, spider):\n        self.user_agent = getattr(spider, "user_agent", self.user_agent)\n\n    def process_request(self, request, spider):\n        if self.user_agent:\n            request.headers[b"User-Agent"] = self.user_agent  # BUG: always overrides spider UA\n'
(WORK / 'scrapy/downloadermiddlewares/useragent.py').write_text(_content_scrapy_downloadermiddlewares_useragent_py)

print('Setup complete: patches applied.')
