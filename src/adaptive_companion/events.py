"""Conservative exam tracking. Unknown dates/end times stay unknown.

Supported: relative days, ISO dates, M月D日, 下周X; HH:mm/数字点 ending
times. This is a local parser, not a claim to understand arbitrary schedules.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone

from .models import Message, ScheduledMessage, utc_now
from .storage import SQLiteStore

SUBJECTS = ("高等数学", "高数", "线性代数", "线代", "英语", "数学", "物理", "化学", "政治", "专业课")


class EventTracker:
    def __init__(self, store: SQLiteStore):
        self.store = store
        self.clarification = ""

    def observe(self, message: Message) -> ScheduledMessage | None:
        self.clarification = ""
        text = message.content.strip()
        # Quoted, hypothetical or third-person events are not our user's plans.
        if re.search(r"[“”\"`]|假如|假设|比如|举例|如果|他|她|朋友|同学", text):
            return None
        zone = timezone(timedelta(minutes=self.store.utc_offset_minutes))
        now = datetime.fromisoformat(message.timestamp).astimezone(zone)
        events = [m for m in self.store.list_memories("long_term", limit=1000)
                  if m["content"].get("event_type") == "exam"
                  and m["content"].get("conversation_id") == message.conversation_id
                  and m["content"].get("status") in {"awaiting_time", "confirmed"}]
        if re.search(r"考完了|考试(?:已经)?结束了|取消.{0,12}考试|不考了|(?:别|不用|不要).{0,8}(?:提醒|关心)", text):
            subject = next((s for s in SUBJECTS if s in text), "")
            cancel_all = not subject and '考试' in text and bool(re.search(r"(?:别|不用|不要).{0,8}(?:提醒|关心)|取消", text))
            for event in events:
                title = event['content']['title']
                if cancel_all or (subject and title == subject + '考试') or (not subject and len(events) == 1):
                    self._save(event['period_key'], {**event['content'], "status": "closed"}, event, message)
            return None
        if re.search(r"不.{0,4}考试|不用.{0,4}关心|别.{0,4}关心|别.{0,6}提醒|不要.{0,6}提醒", text):
            return None
        mentioned = bool(re.search(r"考试|测验", text))
        subject = next((s for s in SUBJECTS if s in text), "")
        title = subject + "考试" if subject else "考试"
        event = next((m for m in events if m['content']['title'] == title), None)
        day = self._day(text, now)
        clock = self._end_clock(text)
        if not day and re.search(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}[日号]", text):
            return None  # Invalid explicit date must not borrow an older valid date.
        if not event and len(events) == 1 and not subject:
            event = events[0]
            title = event['content']['title']
        # A continuation must actually supply schedule data, not unrelated chat.
        if not mentioned and (not event or (day is None and clock is None)):
            return None
        if not mentioned and (event['content']['status'] != 'awaiting_time' or not re.fullmatch(
                r"[\d\s，,。！？?!：:\-/明大后今天年月日号下周一二三四五六七上午中午下午晚上点半分结束考完好是在概应该左右吧]+", text)):
            return None  # Only a terse answer to the time question may fill a pending slot.
        if mentioned and not event:
            # Past-tense stories belong to ordinary memory, not future follow-ups.
            if re.search(r"昨天|前天|上周|上个月|考过|考了|考完", text):
                return None
        old = event['content'] if event else {}
        date_text = day.isoformat() if day else old.get('date')
        # Moving a date does not silently carry over an old end time.
        end_text = old.get('end_at') if not day or date_text == old.get('date') else None
        if date_text and clock:
            end_text = datetime.fromisoformat(date_text).replace(
                hour=clock[0], minute=clock[1], tzinfo=zone).isoformat()
        key = event['period_key'] if event else "event:" + hashlib.sha256((message.conversation_id + title).encode()).hexdigest()[:24]
        content = {
            "event_type": "exam", "title": title, "conversation_id": message.conversation_id,
            "date": date_text, "end_at": end_text,
            "status": "confirmed" if end_text else "awaiting_time",
            "summary": f"用户的{title}；日期：{date_text or '待确认'}；结束时间：{end_text or '待确认'}",
            "asked_for_time": True,
        }
        memory_id = self._save(key, content, event, message)
        if not memory_id:
            return None
        if not end_text:
            if not old.get('asked_for_time') or (day and not clock):
                self.clarification = f"{title}是哪天、几点结束？" if not date_text else f"那{title}大概几点结束？"
            return None
        end = datetime.fromisoformat(end_text)
        if end <= now or end - now > timedelta(days=180):
            return None
        topic = "exam:" + hashlib.sha256(key.encode()).hexdigest()[:20]
        pending = [s for s in self.store.list_scheduled_messages("pending", limit=None)
                   if s.topic == topic and s.conversation_id == message.conversation_id]
        # Repeating an unchanged plan doesn't create or postpone a second job.
        if pending and old.get('end_at') == end_text:
            return None
        for item in pending:
            self.store.update_scheduled_status(item.id, "cancelled")
        due = end + timedelta(minutes=45)
        with self.store.connection() as conn:
            sources = [r[0] for r in conn.execute("SELECT source_message_id FROM memory_sources WHERE memory_id=?", (memory_id,))]
        return ScheduledMessage(
            id=f"sched_{uuid.uuid4().hex}", conversation_id=message.conversation_id,
            created_at=utc_now(), scheduled_at=due.isoformat(), earliest_at=due.isoformat(),
            latest_at=(due + timedelta(hours=24)).isoformat(), topic=topic,
            draft_intent=f"用户的{title}已过确认的结束时间{end_text}，轻轻问一句考得怎么样；不要假装知道成绩。",
            source_memory_ids=sources, reason="exam end time confirmed by user", importance=0.82,
        )

    def _save(self, key: str, content: dict, old: dict | None, message: Message) -> str | None:
        with self.store.connection() as conn:
            sources = [r[0] for r in conn.execute(
                "SELECT s.source_message_id FROM memory_sources s JOIN messages m ON m.id=s.source_message_id WHERE s.memory_id=? ORDER BY m.timestamp,m.rowid", (old['id'],))] if old else []
        sources.append(message.id)
        return self.store.upsert_memory("long_term", key, content, sources[0], message.id,
                                        [content['title'], "event"], 0.85, 0.95, sources)

    @staticmethod
    def _day(text: str, now: datetime):
        iso = re.search(r"(?<!\d)(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", text)
        cn = re.search(r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})[日号]", text)
        if iso or cn:
            match = iso or cn
            year = int(match[1]) if match[1] else now.year
            if not match[1] and '明年' in text:
                year += 1
            try:
                return now.date().replace(year=year, month=int(match[2]), day=int(match[3]))
            except ValueError:
                return None
        for word, delta in (("大后天", 3), ("后天", 2), ("明天", 1), ("今天", 0)):
            if word in text:
                return (now + timedelta(days=delta)).date()
        week = re.search(r"下周([一二三四五六日天])", text)
        if week:
            weekday = "一二三四五六日".find(week[1].replace("天", "日"))
            return (now + timedelta(days=7 - now.weekday() + weekday)).date()
        return None

    @staticmethod
    def _end_clock(text: str):
        clock = r"(?P<period>上午|下午|晚上|中午)?\s*(?P<hour>\d{1,2})(?:[:：](?P<minute>\d{2})|点(?P<half>半)?(?:(?P<cnminute>\d{1,2})分?)?)"
        match = re.search(clock + r"\s*(?:考完|结束|考好)", text) or re.search(r"(?:考完|结束)(?:时间)?(?:是|在|：|:)?\s*" + clock, text)
        if not match:
            return None
        hour = int(match['hour'])
        minute = int(match['minute'] or match['cnminute'] or (30 if match['half'] else 0))
        if hour > 23 or minute > 59 or (match['period'] and not 1 <= hour <= 12):
            return None
        if match['period'] == '晚上' and hour == 12:
            return None  # Midnight's calendar day is ambiguous; ask instead of guessing noon.
        if match['period'] in {"下午", "晚上", "中午"} and hour < 12:
            hour += 12
        return hour, minute
