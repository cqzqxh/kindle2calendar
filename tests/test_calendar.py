import io
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image
from renderer import render_calendar


class CalendarTests(unittest.TestCase):
    def test_month_end_six_weeks_leap_day_and_grayscale(self):
        for stamp in ["2026-03-31T23:59:00", "2028-02-29T00:00:00", "2026-12-31T23:59:00"]:
            now = datetime.fromisoformat(stamp).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            events = [dict(title="很长的中文日程" * 10, day=now.date().isoformat(), time="23:00", member="全家") for _ in range(9)]
            image = Image.open(io.BytesIO(render_calendar(events, now)))
            self.assertEqual(image.mode, "L")
            self.assertEqual(image.size, (1072, 1448))
            self.assertTrue(set(image.tobytes()) <= set(range(0, 256, 17)))


if __name__ == "__main__":
    unittest.main()
