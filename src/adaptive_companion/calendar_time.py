from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta


def week_range(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def month_range(day: date) -> tuple[date, date]:
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])


def add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def resolve_period(query: str, today: date, first_day: date | None = None):
    """Only explicit supported expressions. Unknown wording is not a guessed date."""
    clean = query
    explicit = re.search(r"(?<!\d)(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?(?!\d)", query)
    start = end = None
    if explicit:
        try:
            start = end = date(*map(int, explicit.groups()))
        except ValueError:
            return None
        clean = query[:explicit.start()] + query[explicit.end():]
    else:
        month = re.search(r"(?<!\d)(20\d{2})[-/年](\d{1,2})月?(?![-/\d])", query)
        if month:
            try:
                start, end = month_range(date(int(month[1]), int(month[2]), 1))
            except ValueError:
                return None
            clean = query[:month.start()] + query[month.end():]
        else:
            for phrase, period in (
                ("上个月", month_range(add_months(today, -1))),
                ("上周", week_range(today - timedelta(days=7))),
                ("昨天", (today - timedelta(days=1),) * 2),
                ("前天", (today - timedelta(days=2),) * 2),
            ):
                if phrase in query:
                    start, end = period
                    clean = query.replace(phrase, "")
                    break
    # Ordinal months use the first chat's calendar month, with seven-day buckets
    # inside that month. This convention is surfaced in archive/search metadata.
    if start is None and first_day:
        number = r"([一二三四五六七八九十\d]+)"
        match = re.search(rf"第{number}个?月(?:的)?第{number}周(?:的)?第{number}天", query)
        if match:
            def numeric(value):
                if value.isdigit():
                    return int(value)
                digits = dict(zip("一二三四五六七八九", range(1, 10)))
                if "十" in value:
                    a, _, b = value.partition("十")
                    return digits.get(a, 1) * 10 + digits.get(b, 0)
                return digits.get(value, 0)
            month_n, week_n, day_n = map(numeric, match.groups())
            if 1 <= month_n <= 120 and 1 <= week_n <= 5 and 1 <= day_n <= 7:
                base = add_months(first_day.replace(day=1), month_n - 1)
                candidate = base + timedelta(days=(week_n - 1) * 7 + day_n - 1)
                if candidate.month == base.month:
                    start = end = candidate
                    clean = query[:match.start()] + query[match.end():]
    if start is None:
        return None
    clean = re.sub(r"还记得|记得|聊过|聊天|聊了|那时候|那天|发生|什么|事情|我们|之前|关于|的|吗", " ", clean)
    return start.isoformat(), end.isoformat(), clean.strip()
