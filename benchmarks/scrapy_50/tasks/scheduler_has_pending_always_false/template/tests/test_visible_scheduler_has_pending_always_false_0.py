from unittest.mock import MagicMock, patch
from scrapy.core.scheduler import Scheduler
from scrapy.http import Request
from scrapy.utils.test import get_crawler

def test_has_pending_after_enqueue(tmp_path):
    crawler = get_crawler(settings_dict={
        'SCHEDULER_DEBUG': False,
        'JOBDIR': None,
        'DUPEFILTER_CLASS': 'scrapy.dupefilters.BaseDupeFilter',
    })
    from scrapy.dupefilters import RFPDupeFilter
    scheduler = Scheduler(
        dupefilter=RFPDupeFilter(),
        jobdir=None,
        dqclass=None,
        mqclass=None,
        logunser=False,
        stats=MagicMock(),
        pqclass=None,
        crawler=crawler,
    )
    spider = MagicMock()
    scheduler.open(spider)
    request = Request("https://example.com")
    assert scheduler.enqueue_request(request) is True
    assert scheduler.has_pending_requests(), "Non-empty queue should return True"
