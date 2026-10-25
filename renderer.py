"""Fixed-size PW3 calendar rendering: no browser engine on the Kindle."""
import calendar
import io
import os
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from monthly_themes import THEMES, theme_artwork
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


def upcoming_events(events, now, limit=10):
    """CalDAV events retain ongoing events; legacy timed rows expire at start."""
    today = now.date().isoformat()
    def is_pending(event):
        if event["day"] < today:
            return False
        if event.get("end") and event["end"] != event.get("start"):
            return datetime.fromisoformat(event["end"]) > now
        if not event["time"]:
            return True
        begin = datetime.fromisoformat(event["day"] + "T" + event["time"])
        return begin.replace(tzinfo=now.tzinfo) >= now

    pending = [event for event in events if is_pending(event)]
    result, seen = [], set()
    for event in sorted(pending, key=lambda event: (event["day"], event["time"], event["title"])):
        if event.get("source_id"):
            key = (event["source_id"], event["start"])
            if key in seen:
                continue
            seen.add(key)
        result.append(event)
    return result[:limit]


def render_calendar(events, now, weather=None, *, compact=True, update_interval_minutes=30):
    image = Image.new("L", (WIDTH, HEIGHT), 255)
    d = ImageDraw.Draw(image)
    today = now.date()

    def text(x, y, value, size, fill=0, width=None, *, stroke=1):
        value = " ".join(value.split())
        if width:
            value = fit(d, value, size, width)
        # A one-pixel outline keeps strokes legible with the sleeping panel's frontlight off.
        d.text((x, y), value, font=font(size), fill=fill, stroke_width=stroke, stroke_fill=fill)

    theme = THEMES.get(today.month)
    title = "家庭日历" + (f" · {theme[0]}" if theme else "")
    text(48, 14 if compact else 30, title, 36)
    text(48, 70 if compact else 95, f"{today.year} 年 {today.month} 月", 48 if compact or theme else 68)
    text(714 if compact else 700, 48 if compact else 96, f"{today.day:02d}", 72 if compact or theme else 80)
    text(840, 86 if compact else 130, "星期" + "一二三四五六日"[today.weekday()], 32)
    header_bottom = 144 if compact else 212
    if theme:
        _, caption, filename = theme
        artwork = theme_artwork(filename, 264, 104 if compact else 150)
        x = 424 + (264 - artwork.width) // 2
        y = 6 + ((104 if compact else 150) - artwork.height) // 2
        image.paste(artwork.convert("L"), (x, y), artwork.getchannel("A"))
        caption_width = d.textlength(caption, font=font(22))
        text(round(556 - caption_width / 2), 112 if compact else 170, caption, 22)
    d.line((48, header_bottom, 1024, header_bottom), fill=0, width=3)

    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(today.year, today.month)
    cell_width = 976 / 7
    cell_height = 420 / len(weeks) if compact else 107 if len(weeks) == 6 else 128
    by_day = {}
    for event in events:
        by_day.setdefault(event["day"], []).append(event)
    for col, label in enumerate("一二三四五六日"):
        text(int(48 + col * cell_width + 50), 151 if compact else 230, label, 30, stroke=0)
    for row, week in enumerate(weeks):
        for col, day in enumerate(week):
            x = int(48 + col * cell_width)
            y = int((200 if compact else 284) + row * cell_height)
            d.line((x, y, int(x + cell_width), y), fill=160, width=1)
            if day.month != today.month:
                continue
            if day == today:
                d.rounded_rectangle((x + 4, y + 3, x + 65, y + (43 if compact else 59)), radius=5, fill=0)
            text(x + 13, y if compact else y + 7, str(day.day), 32 if compact else 36, 255 if day == today else 0, stroke=0)
            entries = by_day.get(day.isoformat(), [])
            if entries:
                text(x + 6, y + (40 if compact else 61), entries[0]["title"], 22, width=int(cell_width - 14), stroke=0)
                if len(entries) > 1:
                    text(x + 78, y + (10 if compact else 23), f"+{len(entries)-1}", 22, width=54, stroke=0)

    agenda_top = 640 if compact else 947
    d.line((48, agenda_top, 1024, agenda_top), fill=0, width=3)
    text(48, agenda_top + 18, "近期安排", 38)
    next_update = now + timedelta(minutes=update_interval_minutes)
    next_label = ("次日 " if next_update.date() != today else "") + next_update.strftime("%H:%M")
    text(240, agenda_top + 30,
         f"更新于:{now:%H:%M}, 下次更新:{next_label}", 26, 51)
    upcoming = upcoming_events(events, now, limit=10 if compact else 3)
    if not upcoming:
        text(48, agenda_top + 103, "接下来的日子，留些时间给家人。", 32)
    for i, event in enumerate(upcoming):
        y = 720 + 52 * i if compact else 1034 + 55 * i
        day = date.fromisoformat(event["day"])
        when = "今天" if day == today else f"{day.month}/{day.day}"
        text(48, y + 4, when, 30)
        text(164, y + 4, event["time"] or "全天", 30)
        text(282, y, event["title"], 36, width=506)
        text(816, y + 5, event["member"], 30, width=205)
    if weather is not None:
        d.line((48, 1260, 1024, 1260), fill=0, width=2)
        heading = weather["city"] + "天气"
        text(48, 1268, heading, 30, width=710)
        text(785, 1280, "open-meteo.com", 22, 51)
        days = weather.get("days", [])[:3]
        if not days:
            text(48, 1331, "天气暂不可用，下次同步时重试", 30, 51)
        for i, forecast in enumerate(days):
            x = 48 + i * 335
            forecast_day = date.fromisoformat(forecast["day"])
            label = "今天" if forecast_day == today else "星期" + "一二三四五六日"[forecast_day.weekday()]
            text(x, 1317, f"{label} {forecast_day.month}/{forecast_day.day}", 26)
            image.paste(weather_icon(forecast.get("code")), (x, 1359))
            text(x + 72, 1350, forecast["label"], 30, width=243)
            text(x + 72, 1394, f"{forecast['low']}~{forecast['high']}°", 30, width=243)
    # Quantize antialiasing to the panel's 16 gray levels.
    image = image.point(lambda value: round(value / 17) * 17)
    result = io.BytesIO()
    image.save(result, format="PNG", optimize=True)
    return result.getvalue()
