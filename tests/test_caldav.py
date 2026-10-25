from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from icalendar import Calendar
import recurring_ical_events

from calendar_source import CalendarSyncError, display_window, fetch_events, normalize_event
from preview import main
from renderer import upcoming_events


ENV = {"TECENT_CalDAV_ADDR": "dav.example.test", "TECENT_CalDAV_UID": "account",
       "TECENT_CalDAV_PASSWD": "private-password"}
NOW = datetime(2026, 10, 25, 12, tzinfo=ZoneInfo("Asia/Shanghai"))


def event(body):
    return Calendar.from_ical("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
                             "UID:fixture\r\nSUMMARY:测试活动\r\n" + body +
                             "\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n").walk("VEVENT")[0]


class CalDAVTests(unittest.TestCase):
    def setUp(self):
        self.start, self.end = display_window(NOW)

    def test_window_covers_month_grid_and_upcoming_month(self):
        self.assertEqual(self.start.date().isoformat(), "2026-09-28")
        self.assertEqual(self.end.date().isoformat(), "2026-11-26")

    def test_all_day_exclusive_end_and_timezone_conversion(self):
        rows = normalize_event(event("DTSTART;VALUE=DATE:20261024\r\nDTEND;VALUE=DATE:20261026"), self.start, self.end)
        self.assertEqual([r["day"] for r in rows], ["2026-10-24", "2026-10-25"])
        self.assertTrue(all(r["time"] == "" for r in rows))
        rows = normalize_event(event("DTSTART:20261024T153000Z\r\nDTEND:20261024T170000Z"), self.start, self.end)
        self.assertEqual([(r["day"], r["time"]) for r in rows], [("2026-10-24", "23:30"), ("2026-10-25", "00:00")])

    def test_ongoing_multiday_event_is_only_one_upcoming_item(self):
        rows = normalize_event(event("DTSTART:20261025T030000Z\r\nDTEND:20261027T040000Z"), self.start, self.end)
        self.assertEqual(len(upcoming_events(rows, NOW)), 1)
        self.assertEqual(upcoming_events(rows, NOW)[0]["day"], "2026-10-25")
        self.assertEqual(upcoming_events(rows, NOW.replace(day=27, hour=12)), [])

    def test_cancelled_missing_end_duration_and_malformed(self):
        self.assertEqual(normalize_event(event("DTSTART;VALUE=DATE:20261025\r\nSTATUS:CANCELLED"), self.start, self.end), [])
        self.assertEqual(len(normalize_event(event("DTSTART;VALUE=DATE:20261025"), self.start, self.end)), 1)
        rows = normalize_event(event("DTSTART:20261025T030000Z\r\nDURATION:PT2H"), self.start, self.end)
        self.assertEqual(len(upcoming_events(rows, NOW)), 1)
        with self.assertRaises(ValueError):
            normalize_event(event("DTSTART:20261025T030000Z\r\nDTEND:20261024T030000Z"), self.start, self.end)
        with self.assertRaises(ValueError):
            normalize_event(event("DTSTART:20261025T030000Z\r\nRRULE:FREQ=DAILY"), self.start, self.end)

    def test_recurrence_exdate_and_single_instance_override(self):
        master = event("DTSTART:20261024T030000Z\r\nDTEND:20261024T040000Z\r\nRRULE:FREQ=DAILY;COUNT=4\r\nEXDATE:20261025T030000Z")
        override = event("RECURRENCE-ID:20261026T030000Z\r\nDTSTART:20261026T050000Z\r\nDTEND:20261026T060000Z")
        data = Calendar()
        data.add_component(master)
        data.add_component(override)
        components = recurring_ical_events.of(data).between(self.start, self.end)
        rows = [r for component in components for r in normalize_event(component, self.start, self.end)]
        self.assertEqual(sorted((r["day"], r["time"]) for r in rows),
                         [("2026-10-24", "11:00"), ("2026-10-26", "13:00"), ("2026-10-27", "11:00")])

    def test_fetch_all_calendars_and_fail_closed_on_partial_failure(self):
        source = MagicMock()
        source.search.return_value = [SimpleNamespace(url="https://dav.example.test/event.ics")]
        client = MagicMock()
        data = Calendar()
        data.add_component(event("DTSTART;VALUE=DATE:20261025"))
        client.request.return_value = SimpleNamespace(status=200, raw=data.to_ical())
        client.principal.return_value.calendars.return_value = [source]
        with patch("calendar_source.caldav.DAVClient") as factory:
            factory.return_value.__enter__.return_value = client
            self.assertEqual(len(fetch_events(NOW, ENV)), 1)
            self.assertFalse(source.search.call_args.kwargs["expand"])
            client.request.assert_called_with("https://dav.example.test/event.ics", method="GET")
            self.assertEqual(factory.call_args.kwargs["timeout"], 15)
            broken = MagicMock()
            broken.search.side_effect = RuntimeError("private-password private-event")
            client.principal.return_value.calendars.return_value = [source, broken]
            with self.assertRaises(CalendarSyncError) as error:
                fetch_events(NOW, ENV)
            self.assertNotIn("private-", str(error.exception))
            source.search.return_value = []
            client.principal.return_value.calendars.return_value = [source]
            self.assertEqual(fetch_events(NOW, ENV), [])
            with self.assertRaises(CalendarSyncError):
                fetch_events(NOW, {**ENV, "CALDAV_CALENDAR_NAME": "missing"})
            client.principal.return_value.calendars.return_value = []
            with self.assertRaises(CalendarSyncError):
                fetch_events(NOW, ENV)

    def test_repeated_report_body_does_not_hide_distinct_resources(self):
        source, client = MagicMock(), MagicMock()
        repeated = event("DTSTART;VALUE=DATE:20261025")
        source.search.return_value = [SimpleNamespace(url=f"https://dav.example.test/{i}.ics",
                                                       icalendar_component=repeated) for i in range(3)]
        responses = []
        for i in range(3):
            component = event("DTSTART;VALUE=DATE:20261025")
            component["UID"] = f"unique-{i}"
            resource = Calendar()
            resource.add_component(component)
            responses.append(SimpleNamespace(status=200, raw=resource.to_ical()))
        client.request.side_effect = responses
        client.principal.return_value.calendars.return_value = [source]
        with patch("calendar_source.caldav.DAVClient") as factory:
            factory.return_value.__enter__.return_value = client
            rows = fetch_events(NOW, ENV)
            self.assertEqual(len(rows), 3)
            self.assertEqual(len({r["source_id"] for r in rows}), 3)
            client.request.side_effect = [responses[0], SimpleNamespace(status=404, raw=b"")]
            with self.assertRaises(CalendarSyncError):
                fetch_events(NOW, ENV)

    def test_configuration_validation_and_no_output_replacement_on_failure(self):
        for env in ({}, {**ENV, "CALDAV_URL": "http://example.test"},
                    {**ENV, "CALDAV_URL": "https://user:pass@example.test"}):
            with self.assertRaises(CalendarSyncError):
                fetch_events(NOW, env)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "previous.png"
            output.write_bytes(b"previous image")
            with patch("preview.fetch_events", side_effect=CalendarSyncError("failure")), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(["--caldav", "--output", str(output)])
            self.assertEqual(output.read_bytes(), b"previous image")
            with patch("preview.fetch_events", return_value=[]), patch("preview.load_weather", return_value=None), redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--caldav", "--output", str(output)]), 0)
            self.assertTrue(output.read_bytes().startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
