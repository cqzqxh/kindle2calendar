from contextlib import chdir, redirect_stderr, redirect_stdout
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from preview import load_events, load_weather, main
from renderer import render_calendar


class PreviewTests(unittest.TestCase):
    def test_default_filename_uses_local_preview_time_and_keeps_previous_material(self):
        with tempfile.TemporaryDirectory() as folder, chdir(folder), redirect_stdout(io.StringIO()):
            args = ["--now", "2026-10-24T03:37:00+00:00", "--timezone", "Asia/Shanghai", "--offline"]
            self.assertEqual(main(args), 0)
            first = Path("artifacts/preview_202610241137.png")
            original = first.read_bytes()
            self.assertEqual(main([*args, "--city", "杭州"]), 0)
            second = Path("artifacts/preview_202610241137_2.png")
            self.assertEqual(first.read_bytes(), original)
            self.assertNotEqual(second.read_bytes(), original)
            with Image.open(second) as image:
                self.assertEqual(image.size, (1072, 1448))

    def test_cli_generates_png_without_input_or_network(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "preview.png"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--now", "2026-10-24T12:00:00", "--offline", "--output", str(output)]), 0)
            with Image.open(output) as image:
                self.assertEqual(image.size, (1072, 1448))
                self.assertEqual(image.mode, "L")
                self.assertTrue(set(image.tobytes()) <= set(range(0, 256, 17)))

    def test_cli_automatically_renders_three_days_of_city_weather(self):
        forecast = {"city": "上海", "days": [
            {"day": f"2026-10-{day}", "code": 0, "label": "晴", "low": 17, "high": 23}
            for day in (24, 25, 26)
        ]}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "preview.png"
            with (patch("preview.get_forecast", return_value=forecast) as fetch,
                  patch("preview.render_calendar", wraps=render_calendar) as render,
                  redirect_stdout(io.StringIO())):
                main(["--city", "上海", "--now", "2026-10-24T12:00:00", "--output", str(output)])
            self.assertEqual(fetch.call_args.args[0], "上海")
            self.assertEqual(render.call_args.args[2], forecast)
            self.assertTrue(render.call_args.kwargs["compact"])
            with Image.open(output) as image:
                self.assertEqual(image.size, (1072, 1448))

    def test_weather_failure_keeps_calendar_generation_available(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "preview.png"
            with (patch("weather._get_json", side_effect=OSError("offline")),
                  self.assertLogs("weather", level="WARNING"), redirect_stdout(io.StringIO())):
                self.assertEqual(main(["--city", "上海", "--output", str(output)]), 0)
            self.assertTrue(output.is_file())

    def test_events_are_sorted_and_invalid_date_does_not_replace_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "events.json"
            source.write_text(json.dumps([
                {"title": "later", "day": "2026-10-25", "time": "09:30"},
                {"title": "earlier", "day": "2026-10-24"},
            ]))
            self.assertEqual([event["title"] for event in load_events(source)], ["earlier", "later"])
            source.write_text(json.dumps([{"title": "invalid", "day": "2026-02-30"}]))
            output = Path(folder) / "preview.png"
            output.write_bytes(b"previous output")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["--events", str(source), "--output", str(output)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(output.read_bytes(), b"previous output")

    def test_weather_preview_filters_dates_and_parses_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "weather.json"
            source.write_text(json.dumps({"daily": {
                "time": ["2026-10-23", "2026-10-24", "2026-10-25"],
                "weather_code": [0, 3, 61],
                "temperature_2m_min": [15, 16, 17],
                "temperature_2m_max": [20, 21, 22],
            }}))
            forecast = load_weather(source, "", date(2026, 10, 24))
            self.assertEqual(forecast["city"], "当地")
            self.assertEqual([row["day"] for row in forecast["days"]], ["2026-10-24", "2026-10-25"])
            self.assertEqual(forecast["days"][0]["label"], "阴")

    def test_preview_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "events.json"
            source.write_text("[]")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(["--events", str(source), "--output", str(source)])
            self.assertEqual(source.read_text(), "[]")


if __name__ == "__main__":
    unittest.main()
