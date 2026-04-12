#!/usr/bin/env python3
"""Apply start-state patches to the workspace."""
from pathlib import Path

WORK = Path('/work')

# Patch: scrapy/extensions/corestats.py
_content_scrapy_extensions_corestats_py = '"""\nExtension for collecting core stats like items scraped and start/finish times\n"""\nfrom datetime import datetime, timezone\n\nfrom scrapy import signals\n\n\nclass CoreStats:\n    def __init__(self, stats):\n        self.stats = stats\n        self.start_time = None\n\n    @classmethod\n    def from_crawler(cls, crawler):\n        o = cls(crawler.stats)\n        crawler.signals.connect(o.spider_opened, signal=signals.spider_opened)\n        crawler.signals.connect(o.spider_closed, signal=signals.spider_closed)\n        crawler.signals.connect(o.item_scraped, signal=signals.item_scraped)\n        crawler.signals.connect(o.item_dropped, signal=signals.item_dropped)\n        crawler.signals.connect(o.response_received, signal=signals.response_received)\n        return o\n\n    def spider_opened(self, spider):\n        self.start_time = datetime.now(tz=timezone.utc)\n        self.stats.set_value("start_time", self.start_time, spider=spider)\n\n    def spider_closed(self, spider, reason):\n        finish_time = datetime.now(tz=timezone.utc)\n        elapsed_time_seconds = 0.0  # BUG: always zero\n        self.stats.set_value(\n            "elapsed_time_seconds", elapsed_time_seconds, spider=spider\n        )\n        self.stats.set_value("finish_time", finish_time, spider=spider)\n        self.stats.set_value("finish_reason", reason, spider=spider)\n\n    def item_scraped(self, item, spider):\n        self.stats.inc_value("item_scraped_count", spider=spider)\n\n    def response_received(self, spider):\n        self.stats.inc_value("response_received_count", spider=spider)\n\n    def item_dropped(self, item, spider, exception):\n        reason = exception.__class__.__name__\n        self.stats.inc_value("item_dropped_count", spider=spider)\n        self.stats.inc_value(f"item_dropped_reasons_count/{reason}", spider=spider)\n'
(WORK / 'scrapy/extensions/corestats.py').write_text(_content_scrapy_extensions_corestats_py)

print('Setup complete: patches applied.')
