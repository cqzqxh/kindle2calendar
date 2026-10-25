import io
from datetime import datetime
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image, ImageChops, ImageDraw
from renderer import font, render_calendar, upcoming_events


class UpcomingEventsTests(unittest.TestCase):
    def test_five_minute_refresh_label_crosses_midnight(self):
        now = datetime(2026, 12, 31, 23, 58, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch.object(ImageDraw.ImageDraw, "text", autospec=True) as draw_text:
            render_calendar([], now, update_interval_minutes=5)
        updates = [call.args[2] for call in draw_text.call_args_list if "下次更新:" in call.args[2]]
        self.assertEqual(updates, ["更新于:23:58, 下次更新:次日 00:03"])

    def test_update_times_use_calendar_timezone_and_identify_next_day(self):
        for compact in (True, False):
            for hour, minute, expected in [(12, 10, "12:40"), (23, 50, "次日 00:20")]:
                with self.subTest(compact=compact, hour=hour):
                    now = datetime(2026, 12, 31, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))
                    with patch.object(ImageDraw.ImageDraw, "text", autospec=True) as draw_text:
                        render_calendar([], now, compact=compact)
                    updates = [call for call in draw_text.call_args_list if "下次更新:" in call.args[2]]
                    self.assertEqual(len(updates), 1)
                    call = updates[0]
                    self.assertEqual(call.args[2], f"更新于:{now:%H:%M}, 下次更新:{expected}")
                    x, y = call.args[1]
                    bounds = call.kwargs["font"].getbbox(call.args[2], stroke_width=1)
                    self.assertLessEqual(x + bounds[2], 1024)
                    self.assertLess(y + bounds[3], 720 if compact else 1034)

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
        now = datetime(2026, 11, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
        events = [dict(day=f"2026-11-{i + 2:02d}", time="10:00", title=f"安排{i:02d}", member="全家")
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
            self.assertLess(y + font(36).getbbox(title, stroke_width=1)[3], 1260)
        self.assertEqual(len(upcoming_events(events, now)), 10)
        self.assertEqual(len(upcoming_events(events, now, limit=3)), 3)


class LargeTypeLayoutTests(unittest.TestCase):
    def test_text_stays_in_canvas_and_does_not_overlap_in_dense_layouts(self):
        from datetime import timedelta
        for year, month in ((2027, 2), (2026, 10), (2026, 11)):
            for compact in (True, False):
                with self.subTest(month=month, compact=compact):
                    now = datetime(year, month, 1, 23, 50)
                    events = [dict(day=(now.date() + timedelta(days=i)).isoformat(),
                                   time="23:59", title="长标题验证\n家庭安排不能超出列宽" * 2,
                                   member="家庭成员名称很长") for i in range(12)]
                    weather = dict(city="天气地区名称很长" * 5, days=[dict(
                        day=(now.date() + timedelta(days=i)).isoformat(),
                        code=3, label="多云转小雨", low=-12, high=25) for i in range(3)])
                    boxes = []
                    original = ImageDraw.ImageDraw.text
                    def capture(draw, xy, value, *args, **kwargs):
                        if value:
                            boxes.append((value, draw.textbbox(
                                xy, value, font=kwargs["font"], stroke_width=kwargs["stroke_width"])))
                        return original(draw, xy, value, *args, **kwargs)
                    with patch.object(ImageDraw.ImageDraw, "text", capture):
                        render_calendar(events, now, weather, compact=compact)
                    for i, (value, (left, top, right, bottom)) in enumerate(boxes):
                        self.assertGreaterEqual(left, 0, value)
                        self.assertGreaterEqual(top, 0, value)
                        self.assertLessEqual(right, 1024, value)
                        self.assertLess(bottom, 1448, value)
                        for other, (l2, t2, r2, b2) in boxes[i + 1:]:
                            self.assertFalse(left < r2 and l2 < right and top < b2 and t2 < bottom,
                                             f"{value!r} overlaps {other!r}")


class MonthlyThemeTests(unittest.TestCase):
    def test_month_switches_theme_and_unconfigured_month_keeps_original(self):
        for month, expected, caption in [(10, "家庭日历 · 桂香", "把秋天过慢一点"),
                                         (11, "家庭日历 · 暖食", "天凉了，一起吃顿热饭"),
                                         (12, "家庭日历", None), (1, "家庭日历", None)]:
            with self.subTest(month=month):
                now = datetime(2026 if month > 1 else 2027, month, 1, 10)
                with patch.object(ImageDraw.ImageDraw, "text", autospec=True) as draw_text:
                    render_calendar([], now)
                values = [call.args[2] for call in draw_text.call_args_list]
                self.assertEqual(values[0], expected)
                if caption:
                    self.assertIn(caption, values)

    def test_theme_only_changes_header_and_preserves_panel_format(self):
        for month in (10, 11):
            for compact in (True, False):
                with self.subTest(month=month, compact=compact):
                    now = datetime(2026, month, 1, 10)
                    themed = Image.open(io.BytesIO(render_calendar([], now, compact=compact)))
                    with patch("renderer.THEMES", {}):
                        plain = Image.open(io.BytesIO(render_calendar([], now, compact=compact)))
                    self.assertEqual(themed.size, (1072, 1448))
                    self.assertEqual(themed.mode, "L")
                    self.assertTrue(all(value % 17 == 0 for value in themed.tobytes()))
                    divider = 144 if compact else 212
                    self.assertIsNone(ImageChops.difference(themed, plain).crop(
                        (0, divider, 1072, 1448)).getbbox())
                    self.assertIsNotNone(ImageChops.difference(themed, plain).getbbox())
