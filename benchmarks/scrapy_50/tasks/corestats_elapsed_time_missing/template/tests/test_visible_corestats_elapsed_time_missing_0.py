import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from scrapy.extensions.corestats import CoreStats

def test_elapsed_time_is_nonzero():
    stats = {}
    mock_stats = MagicMock()
    mock_stats.set_value.side_effect = lambda k, v, **kw: stats.update({k: v})

    ext = CoreStats(mock_stats)
    spider = MagicMock()

    start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    finish = datetime(2024, 1, 1, 0, 0, 5, tzinfo=timezone.utc)

    ext.start_time = start
    with patch('scrapy.extensions.corestats.datetime') as mock_dt:
        mock_dt.now.return_value = finish
        ext.spider_closed(spider, 'finished')

    elapsed = stats.get('elapsed_time_seconds', 0)
    assert elapsed == 5.0, f"Expected 5.0, got {elapsed}"
