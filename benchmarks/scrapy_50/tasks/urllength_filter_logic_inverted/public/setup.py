#!/usr/bin/env python3
"""Apply start-state patches to the workspace."""
from pathlib import Path

WORK = Path('/work')

# Patch: scrapy/spidermiddlewares/urllength.py
_content_scrapy_spidermiddlewares_urllength_py = '"""\nUrl Length Spider Middleware\n\nSee documentation in docs/topics/spider-middleware.rst\n"""\n\nimport logging\n\nfrom scrapy.exceptions import NotConfigured\nfrom scrapy.http import Request\n\nlogger = logging.getLogger(__name__)\n\n\nclass UrlLengthMiddleware:\n    def __init__(self, maxlength):\n        self.maxlength = maxlength\n\n    @classmethod\n    def from_settings(cls, settings):\n        maxlength = settings.getint("URLLENGTH_LIMIT")\n        if not maxlength:\n            raise NotConfigured\n        return cls(maxlength)\n\n    def process_spider_output(self, response, result, spider):\n        return (r for r in result or () if self._filter(r, spider))\n\n    async def process_spider_output_async(self, response, result, spider):\n        async for r in result or ():\n            if self._filter(r, spider):\n                yield r\n\n    def _filter(self, request, spider):\n        if isinstance(request, Request) and len(request.url) < self.maxlength:\n            logger.info(\n                "Ignoring link (url length > %(maxlength)d): %(url)s ",\n                {"maxlength": self.maxlength, "url": request.url},\n                extra={"spider": spider},\n            )\n            spider.crawler.stats.inc_value(\n                "urllength/request_ignored_count", spider=spider\n            )\n            return False\n        return True\n'
(WORK / 'scrapy/spidermiddlewares/urllength.py').write_text(_content_scrapy_spidermiddlewares_urllength_py)

print('Setup complete: patches applied.')
