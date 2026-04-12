from unittest.mock import MagicMock
from scrapy.http import Request
from scrapy.core.scheduler import Scheduler
from scrapy.dupefilters import RFPDupeFilter
from scrapy.utils.test import get_crawler

def test_dont_filter_enqueues_duplicate():
    crawler = get_crawler()
    scheduler = Scheduler(
        dupefilter=RFPDupeFilter(), jobdir=None,
        dqclass=None, mqclass=None, logunser=False,
        stats=MagicMock(), pqclass=None, crawler=crawler,
    )
    scheduler.open(MagicMock())
    req1 = Request('https://example.com', dont_filter=False)
    req2 = Request('https://example.com', dont_filter=True)
    result1 = scheduler.enqueue_request(req1)
    result2 = scheduler.enqueue_request(req2)
    assert result1 is True, "First request should be enqueued"
    assert result2 is True, "dont_filter=True should bypass dedup"
