"""Read-only CalDAV source; never treat a failed query as an empty calendar."""
import calendar
import os
from datetime import date, datetime, time, timedelta
from urllib.parse import urlsplit

import caldav
from icalendar import Calendar
import recurring_ical_events


class CalendarSyncError(RuntimeError):
    """Safe to display without including credentials or source content."""


def display_window(now):
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(now.year, now.month)
    start = datetime.combine(weeks[0][0], time.min, now.tzinfo)
    end_day = max(weeks[-1][-1] + timedelta(days=1), now.date() + timedelta(days=32))
    return start, datetime.combine(end_day, time.min, now.tzinfo)


def normalize_event(component, start, end):
    if str(component.get("STATUS", "")).upper() == "CANCELLED":
        return []
    if component.get("RRULE") or component.get("RDATE"):
        raise ValueError("Unexpanded recurrence")
    begin = component.decoded("DTSTART")
    all_day = isinstance(begin, date) and not isinstance(begin, datetime)
    finish = component.decoded("DTEND") if "DTEND" in component else None
    if finish is None:
        duration = component.decoded("DURATION") if "DURATION" in component else None
        finish = begin + (duration if duration is not None else timedelta(days=1) if all_day else timedelta(0))
    if all_day != (isinstance(finish, date) and not isinstance(finish, datetime)):
        raise ValueError("Mismatched event date types")
    def local(value):
        if isinstance(value, datetime):
            return value.replace(tzinfo=start.tzinfo) if value.tzinfo is None else value.astimezone(start.tzinfo)
        return datetime.combine(value, time.min, start.tzinfo)
    begin, finish = local(begin), local(finish)
    if finish < begin:
        raise ValueError("Negative event duration")
    if begin >= end or (finish <= start and begin < start):
        return []
    title = str(component.get("SUMMARY", "")).strip() or "未命名日程"
    uid = str(component.get("UID", ""))
    if not uid:
        raise ValueError("Missing event UID")
    last_day = (finish - timedelta(microseconds=1)).date() if finish > begin else begin.date()
    day = max(begin.date(), start.date())
    last_day = min(last_day, (end - timedelta(microseconds=1)).date())
    rows = []
    while day <= last_day:
        rows.append(dict(title=title, day=day.isoformat(),
                         time="" if all_day else begin.strftime("%H:%M") if day == begin.date() else "00:00",
                         member="", source_id=uid, start=begin.isoformat(), end=finish.isoformat(),
                         all_day=all_day))
        day += timedelta(days=1)
    return rows


def fetch_events(now, environ=None):
    env = os.environ if environ is None else environ
    url = (env.get("CALDAV_URL") or env.get("TECENT_CalDAV_ADDR") or "").strip()
    username = (env.get("CALDAV_USERNAME") or env.get("TECENT_CalDAV_UID") or "").strip()
    password = env.get("CALDAV_PASSWORD") or env.get("TECENT_CalDAV_PASSWD") or ""
    if not all((url, username, password)):
        raise CalendarSyncError("请配置 CalDAV 地址、账号和专用密码。")
    if "://" not in url:
        url = "https://" + url
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CalendarSyncError("CalDAV 地址必须为不含账号、密码和查询参数的 HTTPS 地址。")
    start, end = display_window(now)
    try:
        with caldav.DAVClient(url=url, username=username, password=password, timeout=15,
                              enable_rfc6764=False, rate_limit_handle=False) as client:
            calendars = client.principal().calendars()
            selected = env.get("CALDAV_CALENDAR_NAME", "").strip()
            if selected:
                calendars = [item for item in calendars if item.name == selected]
                if len(calendars) != 1:
                    raise CalendarSyncError("指定日历不存在或名称不唯一。")
            if not calendars:
                raise CalendarSyncError("未发现可读取的日历。")
            rows, seen = [], set()
            for index, source in enumerate(calendars):
                # Tencent REPORT can repeat one event's body for distinct hrefs.
                # Use REPORT only to discover hrefs, then GET each full resource.
                objects = source.search(start=start, end=end, event=True, expand=False)
                data, fetched = Calendar(), set()
                for obj in objects:
                    href = str(obj.url)
                    if href in fetched:
                        continue
                    fetched.add(href)
                    response = client.request(href, method="GET")
                    if response.status != 200:
                        raise ValueError("Incomplete calendar resource")
                    resource = Calendar.from_ical(response.raw)
                    if resource.name != "VCALENDAR" or not resource.walk("VEVENT"):
                        raise ValueError("Missing calendar event")
                    for component in resource.subcomponents:
                        data.add_component(component)
                # Expand only the authoritative GET bodies, including exceptions.
                for component in recurring_ical_events.of(data).between(start, end):
                    for row in normalize_event(component, start, end):
                        row["source_id"] = f"{index}:{row['source_id']}"
                        key = (index, row["source_id"], row["start"], row["day"])
                        if key not in seen:
                            seen.add(key)
                            rows.append(row)
            return sorted(rows, key=lambda row: (row["day"], row["time"], row["title"]))
    except CalendarSyncError:
        raise
    except Exception:
        # DAV exceptions can contain private URLs, XML and event bodies.
        raise CalendarSyncError("CalDAV 读取失败，请检查连接、专用密码及日历数据；未生成新图片。") from None
