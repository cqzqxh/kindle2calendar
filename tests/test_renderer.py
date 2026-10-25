from datetime import datetime
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import ImageDraw
from renderer import font, render_calendar, upcoming_events


class UpcomingEventsTests(unittest.TestCase):
    def test_expired_events_are_removed_before_selecting_in_time_order(self):
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
                         ["夕夕跳舞", "英语课", "绘本/手工", "写字"])
        after_start = at_start.replace(second=1)
        self.assertEqual([event["title"] for event in upcoming_events(events, after_start)],
                         ["英语课", "绘本/手工", "写字"])

    def test_all_day_events_remain_until_end_of_day(self):
        events = [{"day": "2026-10-24", "time": "", "title": "全天事项"}]
        self.assertEqual(upcoming_events(events, datetime(2026, 10, 24, 23, 59)), events)
        self.assertEqual(upcoming_events(events, datetime(2026, 10, 25)), [])

    def test_compact_six_week_month_fits_ten_agenda_rows_above_weather(self):
        now = datetime(2026, 3, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
        events = [dict(day=f"2026-03-{i + 2:02d}", time="10:00", title=f"安排{i:02d}", member="全家")
                  for i in range(12)]
        calls = []
        original = ImageDraw.ImageDraw.text
        def capture(draw, xy, value, *args, **kwargs):
            calls.append((xy, value))
            return original(draw, xy, value, *args, **kwargs)
        with patch.object(ImageDraw.ImageDraw, "text", capture):
            render_calendar(events, now, {"city": "当地", "days": []})
        rows = [(xy, title) for xy, title in calls if xy[1] >= 720 and title.startswith("安排")]
        self.assertEqual([title for _, title in rows], [f"安排{i:02d}" for i in range(10)])
        for (x, y), title in rows:
            self.assertLess(y + font(28).getbbox(title)[3], 1260)
        self.assertEqual(len(upcoming_events(events, now)), 10)
        self.assertEqual(len(upcoming_events(events, now, limit=3)), 3)
