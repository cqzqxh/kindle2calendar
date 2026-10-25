from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from renderer import upcoming_events


class UpcomingEventsTests(unittest.TestCase):
    def test_expired_events_are_removed_before_selecting_three_in_time_order(self):
        events = [
            {"day": "2026-10-25", "time": "17:00", "title": "写字"},
            {"day": "2026-10-25", "time": "12:30", "title": "绘本/手工"},
            {"day": "2026-10-24", "time": "12:30", "title": "英语课"},
            {"day": "2026-10-24", "time": "09:00", "title": "夕夕跳舞"},
            {"day": "2026-10-23", "time": "", "title": "昨天的事项"},
        ]
        timezone = ZoneInfo("Asia/Shanghai")
        at_start = datetime(2026, 10, 24, 9, 0, tzinfo=timezone)
        self.assertEqual([event["title"] for event in upcoming_events(events, at_start)],
                         ["夕夕跳舞", "英语课", "绘本/手工"])
        after_start = at_start.replace(second=1)
        self.assertEqual([event["title"] for event in upcoming_events(events, after_start)],
                         ["英语课", "绘本/手工", "写字"])

    def test_all_day_events_remain_until_end_of_day(self):
        events = [{"day": "2026-10-24", "time": "", "title": "全天事项"}]
        self.assertEqual(upcoming_events(events, datetime(2026, 10, 24, 23, 59)), events)
        self.assertEqual(upcoming_events(events, datetime(2026, 10, 25)), [])
