"""Configurable three-day weather with coordinate priority and city fallback."""
import json
import logging
import math
import time
from datetime import date, datetime, timedelta
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

LOG = logging.getLogger(__name__)

WEATHER_LABELS = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "冻雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "强毛毛雨", 56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "中阵雨", 82: "强阵雨", 85: "阵雪", 86: "强阵雪",
    95: "雷雨", 96: "雷雨冰雹", 99: "雷雨冰雹",
}


def parse_daily(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("daily"), dict):
        raise ValueError("Missing daily forecast")
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


class WeatherUnavailable(ValueError):
    """A location or forecast could not be resolved reliably."""


def _get_json(endpoint, params):
    request = Request(endpoint + "?" + urlencode(params), headers={
        "Accept": "application/json", "User-Agent": "KindleFamilyCalendar/1.0",
    })
    for attempt in range(2):
        try:
            with urlopen(request, timeout=5) as response:
                body = response.read(262145)
                if len(body) > 262144:
                    raise ValueError("Weather response too large")
                return json.loads(body)
        except (OSError, HTTPException) as error:
            if attempt or (isinstance(error, HTTPError) and error.code != 429 and error.code < 500):
                raise
            time.sleep(0.2)


def _coordinates(latitude, longitude):
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        raise ValueError("Invalid coordinates")
    lat, lon = float(latitude), float(longitude)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid coordinates")
    return lat, lon


def _name(value):
    return " ".join(value.strip().casefold().split()).removesuffix("市")


def resolve_location(city="", latitude=None, longitude=None):
    city = city.strip()
    try:
        lat, lon = _coordinates(latitude, longitude)
        return {"city": city or "当地", "latitude": lat, "longitude": lon}
    except (TypeError, ValueError, OverflowError):
        if any(value is not None and str(value).strip() for value in (latitude, longitude)):
            LOG.warning("经纬度不完整或无效，回退到城市查询")
    if not city:
        raise WeatherUnavailable("未配置天气地区，请设置 WEATHER_CITY 或完整经纬度")

    query = city.replace("，", ",")
    payload = _get_json("https://geocoding-api.open-meteo.com/v1/search", {
        "name": query, "language": "zh", "count": 100,
    })
    candidates = []
    for item in payload.get("results", []):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        try:
            lat, lon = _coordinates(item.get("latitude"), item.get("longitude"))
        except (TypeError, ValueError, OverflowError):
            continue
        candidates.append({**item, "latitude": lat, "longitude": lon})
    matches = [item for item in candidates if _name(item["name"]) == _name(query.split(",")[0])]
    if matches:
        candidates = matches
    places = [item for item in candidates if str(item.get("feature_code", "")).startswith("PPL")]
    if places:
        candidates = places
    # A city matching its administrative region is distinct from same-named villages.
    administrative = [item for item in candidates if any(
        _name(item["name"]) == _name(str(item.get(key) or "")) for key in ("admin1", "admin2")
    )]
    if administrative:
        candidates = administrative
    unique = {(item["latitude"], item["longitude"]): item for item in candidates}
    if not unique:
        raise WeatherUnavailable("未找到天气城市，请检查城市名称或填写经纬度")
    if len(unique) != 1:
        raise WeatherUnavailable("天气城市有多个匹配，请补充国家 / 省份或填写经纬度")
    item = next(iter(unique.values()))
    return {"city": item["name"], "latitude": item["latitude"], "longitude": item["longitude"]}


def get_forecast(city="", latitude=None, longitude=None, timezone="Asia/Shanghai", today=None):
    tz = ZoneInfo(timezone)
    today = today or datetime.now(tz).date()
    forecast = {"city": city.split(",")[0].split("，")[0].strip() or "当地", "days": []}
    try:
        location = resolve_location(city, latitude, longitude)
        forecast["city"] = location["city"]
        payload = _get_json("https://api.open-meteo.com/v1/forecast", {
            "latitude": location["latitude"], "longitude": location["longitude"],
            "timezone": timezone, "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=2)).isoformat(),
            "daily": "weather_code,temperature_2m_min,temperature_2m_max",
        })
        rows = parse_daily(payload)
        by_day = {row["day"]: row for row in rows}
        wanted = [(today + timedelta(days=i)).isoformat() for i in range(3)]
        if not set(wanted) <= by_day.keys() or len(by_day) != len(rows):
            raise WeatherUnavailable("预报未覆盖图片日期起三天；历史预览请使用 --weather 输入对应数据")
        forecast["days"] = [
            {**by_day[day], "label": WEATHER_LABELS.get(by_day[day]["code"], "天气未知")}
            for day in wanted
        ]
    except WeatherUnavailable as error:
        LOG.warning("%s", error)
    except (OSError, HTTPException, ValueError, KeyError, TypeError, AttributeError, OverflowError) as error:
        LOG.warning("天气请求或数据校验失败（%s），本次仍生成日历", type(error).__name__)
    return forecast
