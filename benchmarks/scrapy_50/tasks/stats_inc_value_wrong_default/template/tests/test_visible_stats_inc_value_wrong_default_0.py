from scrapy.statscollectors import MemoryStatsCollector
from unittest.mock import MagicMock

def test_inc_new_key_starts_at_one():
    crawler = MagicMock()
    stats = MemoryStatsCollector(crawler)
    stats.inc_value('pages_crawled')
    assert stats.get_value('pages_crawled') == 1

def test_inc_existing_key_accumulates():
    crawler = MagicMock()
    stats = MemoryStatsCollector(crawler)
    stats.inc_value('count', 3)
    stats.inc_value('count', 2)
    assert stats.get_value('count') == 5
