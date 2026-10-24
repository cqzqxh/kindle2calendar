import unittest

from weather import parse_daily


def daily():
    return {"daily": {
        "time": ["2026-10-24", "2026-10-25", "2026-10-26"],
        "weather_code": [0, 3, 61],
        "temperature_2m_min": [17.2, 16.8, 15.0],
        "temperature_2m_max": [23.2, 22.9, 21.1],
    }}


class WeatherTests(unittest.TestCase):
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
