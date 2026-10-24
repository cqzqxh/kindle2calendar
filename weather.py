"""Shared forecast parsing for PNG generation; no fixed region or local cache."""
import math
from datetime import date

WEATHER_LABELS = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "冻雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "强毛毛雨", 56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "中阵雨", 82: "强阵雨", 85: "阵雪", 86: "强阵雪",
    95: "雷雨", 96: "雷雨冰雹", 99: "雷雨冰雹",
}


def parse_daily(payload):
    daily = payload["daily"]
    fields = [daily[key] for key in ("time", "weather_code", "temperature_2m_min", "temperature_2m_max")]
    if not all(isinstance(field, list) for field in fields) or len({len(field) for field in fields}) != 1:
        raise ValueError("Unexpected forecast arrays")
    days = []
    for day, code, low, high in zip(*fields):
        date.fromisoformat(day)
        if (type(code) is not int or type(low) not in (int, float) or type(high) not in (int, float)
                or not math.isfinite(low) or not math.isfinite(high) or not -100 <= low <= high <= 70):
            raise ValueError("Invalid forecast values")
        days.append(dict(day=day, code=code, low=round(low), high=round(high)))
    return days
