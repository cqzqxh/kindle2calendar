"""Fixed-size PW3 calendar rendering: no browser engine on the Kindle."""
import calendar
import io
import os
from datetime import date
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from weather_icons import weather_icon

WIDTH, HEIGHT = 1072, 1448


@lru_cache(maxsize=16)
def font(size):
    candidates = [os.environ.get("FONT_PATH", ""),
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  "/System/Library/Fonts/Hiragino Sans GB.ttc"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            # Noto's face 2 is Simplified Chinese; the macOS fallback has one face.
            return ImageFont.truetype(candidate, size, index=2 if "NotoSansCJK" in candidate else 0)
    raise RuntimeError("Chinese font missing. Install fonts-noto-cjk or set FONT_PATH.")


def fit(draw, text, size, width):
    if draw.textlength(text, font=font(size)) <= width:
        return text
    while text and draw.textlength(text + "…", font=font(size)) > width:
        text = text[:-1]
    return text + "…"


def render_calendar(events, now, weather=None):
    image = Image.new("L", (WIDTH, HEIGHT), 255)
    d = ImageDraw.Draw(image)
    today = now.date()

    def text(x, y, value, size, fill=0, width=None):
        if width:
            value = fit(d, value, size, width)
        d.text((x, y), value, font=font(size), fill=fill)

    text(48, 30, "家庭日历", 38)
    clock = "更新于 " + now.strftime("%H:%M")
    clock_size = 44
    text(int(1024 - d.textlength(clock, font=font(clock_size))), 24, clock, clock_size)
    text(48, 95, f"{today.year} 年 {today.month} 月", 72)
    text(700, 102, f"{today.day:02d}", 82)
    text(840, 130, "星期" + "一二三四五六日"[today.weekday()], 32)
    d.line((48, 212, 1024, 212), fill=0, width=3)

    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(today.year, today.month)
    cell_width = 976 / 7
    cell_height = 107 if len(weeks) == 6 else 128
    by_day = {}
    for event in events:
        by_day.setdefault(event["day"], []).append(event)
    for col, label in enumerate("一二三四五六日"):
        text(int(48 + col * cell_width + 52), 230, label, 26)
    for row, week in enumerate(weeks):
        for col, day in enumerate(week):
            x = int(48 + col * cell_width)
            y = 284 + row * cell_height
            d.line((x, y, int(x + cell_width), y), fill=160, width=1)
            if day.month != today.month:
                continue
            if day == today:
                d.rounded_rectangle((x + 4, y + 6, x + 62, y + 58), radius=5, fill=0)
            text(x + 13, y + 7, str(day.day), 32, 255 if day == today else 0)
            entries = by_day.get(day.isoformat(), [])
            if entries:
                text(x + 6, y + 61, entries[0]["title"], 20, width=int(cell_width - 14))
                if len(entries) > 1:
                    text(x + 75, y + 23, f"+{len(entries)-1}", 18)

    d.line((48, 947, 1024, 947), fill=0, width=3)
    text(48, 969, "近期安排", 34)
    upcoming = [e for e in events if e["day"] >= today.isoformat()]
    if not upcoming:
        text(48, 1050, "接下来的日子，留些时间给家人。", 30)
        text(48, 1110, "在手机端添加第一条日程。", 25, 80)
    limit = 3 if weather is not None else 5
    for i, event in enumerate(upcoming[:limit]):
        y = 1034 + 55 * i
        day = date.fromisoformat(event["day"])
        when = "今天" if day == today else f"{day.month}/{day.day}"
        text(48, y, when, 25)
        text(152, y, event["time"] or "全天", 25)
        text(260, y, event["title"], 28, width=520)
        text(813, y + 2, event["member"], 23, width=208)
    if len(upcoming) > limit:
        text(48, 1207 if weather is not None else 1352,
             f"另有 {len(upcoming)-limit} 项安排，请在手机端查看", 22, 70)
    if weather is not None:
        d.line((48, 1260, 1024, 1260), fill=0, width=2)
        heading = weather["city"] + "天气"
        text(48, 1272, heading, 28)
        text(795, 1280, "open-meteo.com", 20, 70)
        days = weather.get("days", [])[:3]
        if not days:
            text(48, 1331, "天气暂不可用，下次同步时重试", 26, 70)
        for i, forecast in enumerate(days):
            x = 48 + i * 335
            forecast_day = date.fromisoformat(forecast["day"])
            label = "今天" if forecast_day == today else "星期" + "一二三四五六日"[forecast_day.weekday()]
            text(x, 1320, f"{label} {forecast_day.month}/{forecast_day.day}", 23)
            image.paste(weather_icon(forecast.get("code")), (x, 1359))
            text(x + 72, 1350, forecast["label"], 27, width=243)
            text(x + 72, 1391, f"{forecast['low']}~{forecast['high']}°", 24, width=243)
    # Quantize antialiasing to the panel's 16 gray levels.
    image = image.point(lambda value: round(value / 17) * 17)
    result = io.BytesIO()
    image.save(result, format="PNG", optimize=True)
    return result.getvalue()
