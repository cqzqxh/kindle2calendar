from datetime import date
import json
import unittest
from unittest.mock import patch
from urllib.error import URLError
from zoneinfo import ZoneInfoNotFoundError

from weather import _get_json, get_forecast, parse_daily


def daily():
    return {"daily": {
        "time": ["2026-10-24", "2026-10-25", "2026-10-26"],
        "weather_code": [0, 3, 61],
        "temperature_2m_min": [17.2, 16.8, 15.0],
        "temperature_2m_max": [23.2, 22.9, 21.1],
    }}


def city_result():
    return {"results": [{"name": "上海", "latitude": 31.23, "longitude": 121.47,
                         "admin1": "上海市", "admin2": "上海市",
                         "feature_code": "PPLA", "timezone": "Asia/Shanghai"}]}


class WeatherTests(unittest.TestCase):
    today = date(2026, 10, 24)

    def test_valid_coordinates_take_priority_including_zero(self):
        with patch("weather._get_json", return_value=daily()) as request:
            result = get_forecast("", "0", "0", today=self.today)
        self.assertEqual(result["city"], "当地")
        self.assertEqual(len(result["days"]), 3)
        request.assert_called_once()
        endpoint, params = request.call_args.args
        self.assertEqual(endpoint, "https://api.open-meteo.com/v1/forecast")
        self.assertEqual((params["latitude"], params["longitude"]), (0, 0))

    def test_city_lookup_and_forecast_use_explicit_timezone(self):
        location = city_result()
        location["results"][0]["timezone"] = "Europe/Paris"
        with patch("weather._get_json", side_effect=[location, daily()]) as request:
            result = get_forecast("上海", today=self.today)
        self.assertEqual(result["days"][0]["label"], "晴")
        self.assertEqual(request.call_args_list[0].args[1]["name"], "上海")
        self.assertEqual(request.call_args_list[1].args[1]["timezone"], "Asia/Shanghai")

    def test_partial_and_invalid_coordinates_all_fall_back_to_city(self):
        for latitude, longitude in ((None, "121"), ("31", None), ("nan", "121"),
                                    ("91", "121"), ("31", "181"), ("invalid", "121")):
            with self.subTest(latitude=latitude, longitude=longitude):
                with (patch("weather._get_json", side_effect=[city_result(), daily()]) as request,
                      self.assertLogs("weather", level="WARNING")):
                    result = get_forecast("上海", latitude, longitude, today=self.today)
                self.assertEqual(len(result["days"]), 3)
                self.assertEqual(request.call_count, 2)
                params = request.call_args.args[1]
                self.assertEqual((params["latitude"], params["longitude"]), (31.23, 121.47))

    def test_missing_location_does_not_guess_or_request_network(self):
        with patch("weather._get_json") as request, self.assertLogs("weather", level="WARNING"):
            result = get_forecast(today=self.today)
        request.assert_not_called()
        self.assertEqual(result["days"], [])

    def test_missing_or_ambiguous_city_does_not_select_first_result(self):
        ambiguous = city_result()
        ambiguous["results"].append({**ambiguous["results"][0], "latitude": 20, "longitude": 100})
        for location in ({"results": []}, ambiguous):
            with patch("weather._get_json", return_value=location) as request, self.assertLogs("weather", level="WARNING"):
                result = get_forecast("上海", today=self.today)
            request.assert_called_once()
            self.assertEqual(result["days"], [])

    def test_city_matches_its_administrative_region_instead_of_same_named_village(self):
        location = city_result()
        location["results"].insert(0, {"name": "上海", "latitude": 29, "longitude": 121,
                                      "feature_code": "PPL", "admin1": "浙江", "admin2": "绍兴市"})
        with patch("weather._get_json", side_effect=[location, daily()]) as request:
            result = get_forecast("上海", today=self.today)
        self.assertEqual(len(result["days"]), 3)
        self.assertEqual(request.call_args.args[1]["latitude"], 31.23)

    def test_forecast_must_cover_preview_dates(self):
        with patch("weather._get_json", return_value=daily()), self.assertLogs("weather", level="WARNING"):
            result = get_forecast(latitude=0, longitude=0, today=date(2026, 10, 25))
        self.assertEqual(result["days"], [])

    def test_preview_requests_weather_for_its_own_three_day_interval(self):
        payload = daily()
        payload["daily"]["time"] = ["2026-10-23", "2026-10-24", "2026-10-25"]
        with patch("weather._get_json", return_value=payload) as request:
            result = get_forecast(latitude=0, longitude=0, today=date(2026, 10, 23))
        params = request.call_args.args[1]
        self.assertEqual((params["start_date"], params["end_date"]), ("2026-10-23", "2026-10-25"))
        self.assertEqual([day["day"] for day in result["days"]], payload["daily"]["time"])

    def test_network_error_degrades_only_weather(self):
        with patch("weather._get_json", side_effect=OSError("offline")), self.assertLogs("weather", level="WARNING"):
            result = get_forecast("上海", today=self.today)
        self.assertEqual(result["days"], [])

    def test_invalid_timezone_is_not_silently_replaced(self):
        with self.assertRaises(ZoneInfoNotFoundError):
            get_forecast("上海", timezone="Invalid/Timezone", today=self.today)

    def test_transient_http_error_retries_with_timeout(self):
        with patch("weather.urlopen") as request, patch("weather.time.sleep"):
            response = request.return_value.__enter__.return_value
            response.read.return_value = json.dumps(daily()).encode()
            request.side_effect = [URLError("offline"), request.return_value]
            self.assertEqual(_get_json("https://example.test", {"name": "上海"}), daily())
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args.kwargs["timeout"], 5)

    def test_forecast_dates_and_temperature_rounding(self):
        rows = parse_daily(daily())
        self.assertEqual([row["day"] for row in rows], daily()["daily"]["time"])
        self.assertEqual((rows[0]["low"], rows[0]["high"]), (17, 23))

    def test_invalid_forecasts_are_rejected(self):
        for bad in (None, float("nan"), float("inf"), "17"):
            payload = daily()
            payload["daily"]["temperature_2m_min"][0] = bad
            with self.assertRaises(ValueError):
                parse_daily(payload)
        payload = daily()
        payload["daily"]["weather_code"].pop()
        with self.assertRaises(ValueError):
            parse_daily(payload)
        payload = daily()
        payload["daily"]["time"][0] = "2026-02-30"
        with self.assertRaises(ValueError):
            parse_daily(payload)


if __name__ == "__main__":
    unittest.main()
