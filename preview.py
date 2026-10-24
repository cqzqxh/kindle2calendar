"""Render a local PNG directly, without starting a service or publishing data."""
import argparse
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from renderer import render_calendar
from weather import WEATHER_LABELS, parse_daily


def load_events(path):
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("events 必须是 JSON 数组")
    events = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("每条日程必须是 JSON 对象")
        title, day = item.get("title"), item.get("day")
        clock, member = item.get("time", ""), item.get("member", "")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("日程 title 必须是非空字符串")
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("日程 day 必须为 YYYY-MM-DD")
        date.fromisoformat(day)
        if not isinstance(clock, str) or not isinstance(member, str):
            raise ValueError("日程 time 和 member 必须是字符串")
        if clock:
            if not re.fullmatch(r"\d{2}:\d{2}", clock):
                raise ValueError("日程 time 必须为 HH:mm 或空字符串")
            datetime.strptime(clock, "%H:%M")
        events.append(dict(title=title.strip(), day=day, time=clock, member=member))
    return sorted(events, key=lambda event: (event["day"], event["time"], event["title"]))


def load_weather(path, city, today):
    forecast = dict(city=city or "当地", days=[])
    if path is None:
        return forecast
    payload = json.loads(path.read_text(encoding="utf-8"))
    wanted = {(today + timedelta(days=i)).isoformat() for i in range(3)}
    rows = parse_daily(payload)
    forecast["days"] = [
        {**row, "label": WEATHER_LABELS.get(row["code"], "天气未知")}
        for row in sorted(rows, key=lambda row: row["day"]) if row["day"] in wanted
    ]
    return forecast


def main(argv=None):
    parser = argparse.ArgumentParser(description="直接生成家庭日历 PNG，不启动 Web 服务")
    parser.add_argument("--events", type=Path, help="已规范化的日程 JSON 数组；省略则显示空日历")
    parser.add_argument("--weather", type=Path, help="Open-Meteo daily JSON；省略则显示天气不可用")
    parser.add_argument("--city", default=os.environ.get("WEATHER_CITY", ""), help="仅设置预览的地区标题")
    parser.add_argument("--timezone", default=os.environ.get("TIMEZONE") or "Asia/Shanghai")
    parser.add_argument("--now", help="指定预览时间，ISO 8601 格式；无时区时使用 --timezone")
    parser.add_argument("--output", type=Path, help="输出路径；默认 artifacts/preview_YYYYMMDDHHmm.png")
    args = parser.parse_args(argv)
    try:
        tz = ZoneInfo(args.timezone)
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(tz)
        now = now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz)
        output = args.output or Path(f"artifacts/preview_{now:%Y%m%d%H%M}.png")
        if output.resolve() in {path.resolve() for path in (args.events, args.weather) if path}:
            raise ValueError("输出路径不能覆盖输入 JSON")
        events = load_events(args.events)
        weather = load_weather(args.weather, args.city.strip(), now.date())
        png = render_calendar(events, now, weather)
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.output:
            output.write_bytes(png)
        else:
            base = output
            suffix = 2
            while True:
                try:
                    with output.open("xb") as target:
                        target.write(png)
                    break
                except FileExistsError:
                    output = base.with_name(f"{base.stem}_{suffix}.png")
                    suffix += 1
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        parser.exit(2, "无法生成预览，请检查输入文件、日期、时区、字体和输出路径。\n")
    print(f"日历图片已生成：{output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
