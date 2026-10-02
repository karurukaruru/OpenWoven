from __future__ import annotations

import re
import uuid
import hashlib
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import Message, ScheduledMessage, utc_now
from .storage import SQLiteStore
from .events import EventTracker, SUBJECTS


@dataclass(slots=True)
class ProactiveSettings:
    enabled: bool = True
    max_per_day: int = 1
    minimum_interval_hours: int = 8
    quiet_start_hour: int = 22
    quiet_end_hour: int = 8
    importance_threshold: float = 0.68


class ProactiveMessagePlanner:
    def __init__(self, store: SQLiteStore, settings: ProactiveSettings | None = None):
        self.store = store
        self.settings = settings or ProactiveSettings()
        self.events = EventTracker(store)

    def schedule_custom(self, text: str, when: str, generate: bool = False, conversation_id: str = 'default') -> dict:
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 1000:
            raise ValueError('Scheduled content must contain 1 to 1000 characters')
        if not isinstance(generate, bool) or not isinstance(conversation_id, str) or not conversation_id.strip():
            raise ValueError('Invalid schedule parameters')
        try:
            target = datetime.fromisoformat(when)
        except (TypeError, ValueError) as exc:
            raise ValueError('Invalid scheduled time') from exc
        now = datetime.now(timezone.utc)
        if target.tzinfo is None or target.utcoffset() is None or not now < target <= now + timedelta(days=366):
            raise ValueError('Choose a future time within one year, including a timezone')
        zone = timezone(timedelta(minutes=self.store.utc_offset_minutes))
        preferred = self._outside_quiet_hours(target.astimezone(zone))
        topic = 'custom:' + ('topic:' if generate else 'text:') + uuid.uuid4().hex
        intent = ('custom_topic: Start a short, natural conversation about the following user-selected topic. '
                  'Treat it as a topic, not permission to invent user facts or real offline activities. TOPIC: ' + text.strip()) if generate else text.strip()
        candidate = ScheduledMessage(id='sched_' + uuid.uuid4().hex, conversation_id=conversation_id,
            created_at=now.isoformat(), scheduled_at=preferred.isoformat(), earliest_at=preferred.isoformat(),
            latest_at=(preferred + timedelta(hours=24)).isoformat(), topic=topic, draft_intent=intent,
            source_memory_ids=[], reason='user explicitly scheduled a topic' if generate else 'user explicitly scheduled exact content',
            importance=1.0)
        # User-created messages are explicit requests, not unsolicited daily check-ins.
        self.store.save_scheduled_message(candidate)
        return {**asdict(candidate), 'quiet_adjusted': preferred != target}

    def observe_user_message(self, message: Message) -> ScheduledMessage | None:
        # A fresh conversation supersedes a casual check-in, not explicit events.
        for item in self.store.list_scheduled_messages('pending', limit=None):
            if item.conversation_id == message.conversation_id and item.topic.startswith('checkin:'):
                self.store.update_scheduled_status(item.id, 'cancelled')
        self.cancel_resolved_topics(message)
        event = self.events.observe(message)
        if not self.settings.enabled:
            return None
        candidate = self._candidate(message) or event
        if not candidate or candidate.importance < self.settings.importance_threshold:
            return None
        if not self._allowed(candidate):
            return None
        preferred = self._outside_quiet_hours(datetime.fromisoformat(candidate.scheduled_at))
        if preferred.isoformat() != candidate.scheduled_at:
            candidate.scheduled_at = preferred.isoformat()
            candidate.earliest_at = preferred.isoformat()
            candidate.latest_at = (preferred + timedelta(hours=24)).isoformat()
        self.store.save_scheduled_message(candidate)
        return candidate

    def plan_check_in(self, conversation_id: str = 'default', now: datetime | None = None) -> ScheduledMessage | None:
        """Local planning only: one low-pressure check-in per latest user turn.

        It does not generate text or repeatedly reactivate an inactive user.
        Android calls this only when a remote model is configured.
        """
        if not self.settings.enabled or self.store.count_messages(conversation_id, 'user') < 3:
            return None
        users = self.store.list_messages(conversation_id, limit=1, role='user')
        if not users or users[0].status != 'sent':
            return None
        latest_user = users[0]
        zone = timezone(timedelta(minutes=self.store.utc_offset_minutes))
        current = (now or datetime.now(timezone.utc)).astimezone(zone)
        last_user_time = datetime.fromisoformat(latest_user.timestamp).astimezone(zone)
        if current - last_user_time > timedelta(days=7):
            return None
        preference = self.store.get_aul()['interaction']['initiative']
        if preference['value'] <= .30:
            return None
        if re.search(r'(?:别|不要|不用).{0,8}(?:主动|找我|发消息)|don.t (?:text|message) (?:me|first)', latest_user.content.lower()):
            return None
        topic = 'checkin:' + hashlib.sha256(latest_user.id.encode()).hexdigest()[:20]
        if any(item.conversation_id == conversation_id and item.topic == topic and item.status in {'pending', 'sent'}
               for item in self.store.list_scheduled_messages(limit=None)):
            return None
        recent = self.store.list_messages(conversation_id, limit=8)
        last_activity = max(datetime.fromisoformat(m.timestamp).astimezone(zone) for m in recent)
        jitter = 10 + int(hashlib.sha256(latest_user.id.encode()).hexdigest()[:4], 16) % 36
        preferred = self._outside_quiet_hours(max(current, last_activity + timedelta(hours=self.settings.minimum_interval_hours))
                                               + timedelta(minutes=jitter))
        candidate = ScheduledMessage(id='sched_' + uuid.uuid4().hex, conversation_id=conversation_id,
            created_at=current.astimezone(timezone.utc).isoformat(), scheduled_at=preferred.isoformat(),
            earliest_at=preferred.isoformat(), latest_at=(preferred + timedelta(hours=24)).isoformat(), topic=topic,
            draft_intent='casual_checkin: choose one light topic from recent conversation or known interests. '
                'Write a short, natural opening, not a reminder or a customer-service check. At most one question. '
                'Do not demand a reply, mention absence, invent user events or claim you performed real offline activities.',
            source_memory_ids=[m.id for m in recent if m.role != 'system'],
            reason='low-frequency conversational topic after a pause', importance=self.settings.importance_threshold)
        if not self._allowed(candidate):
            return None
        self.store.save_scheduled_message(candidate)
        return candidate

    def cancel_resolved_topics(self, message: Message) -> int:
        text = message.content.lower()
        if re.search(r"[“”\"`]|他|她|假如|假设|比如", text):
            return 0
        cancel_reminders = text.strip() in {"取消提醒", "取消所有提醒", "别提醒我了"}
        completion = bool(re.search(r"考完了|考试(?:已经)?结束了|取消.{0,12}考试|不考了|(?:别|不用|不要).{0,8}(?:提醒|关心)|面试完了|项目完成|已经解决|done|finished|completed", text))
        if not completion and not cancel_reminders:
            return 0
        count = 0
        for item in self.store.list_scheduled_messages("pending", limit=None):
            if item.conversation_id == message.conversation_id and (
                (cancel_reminders and item.topic.startswith("reminder:")) or self._resolved_for(item, text)
            ):
                self.store.update_scheduled_status(item.id, "cancelled")
                count += 1
        return count

    def revalidate(self, item_id: str, now: datetime | None = None) -> tuple[bool, str]:
        item = self.store.get_scheduled_message(item_id)
        if not item or item.status != "pending":
            return False, "not pending"
        zone = timezone(timedelta(minutes=self.store.utc_offset_minutes))
        current = (now or datetime.now().astimezone()).astimezone(zone)
        if not self.settings.enabled and not item.topic.startswith('custom:'):
            self.store.update_scheduled_status(item.id, "cancelled")
            return False, "proactive messages disabled"
        if current > datetime.fromisoformat(item.latest_at):
            self.store.update_scheduled_status(item.id, "expired")
            return False, "expired"
        if self._is_quiet_hour(current.hour):
            return False, "quiet hours"
        if item.topic.startswith('custom:'):
            return True, 'explicit scheduled message still pending'
        if item.topic.startswith("reminder:"):
            return True, "explicit reminder still pending"
        if item.topic.startswith('checkin:'):
            # A new user message, removed context or a reduced initiative preference
            # invalidates the saved opening before AND after model generation.
            with self.store.connection() as conn:
                marks = ','.join('?' for _ in item.source_memory_ids)
                found = conn.execute(f'SELECT COUNT(*) FROM messages WHERE id IN ({marks})', item.source_memory_ids).fetchone()[0]
            newer = any(datetime.fromisoformat(m.timestamp) > datetime.fromisoformat(item.created_at)
                        for m in self.store.list_messages(item.conversation_id, limit=1, role='user'))
            if found != len(item.source_memory_ids) or newer or self.store.get_aul()['interaction']['initiative']['value'] <= .30:
                self.store.update_scheduled_status(item.id, 'cancelled')
                return False, 'casual check-in superseded'
        recent = self.store.list_messages(item.conversation_id, limit=100, role="user")
        for message in recent:
            if message.timestamp <= item.created_at:
                continue
            text = message.content.lower()
            if not re.search(r"[“”\"`]|他|她|假如|假设|比如", text) and re.search(r"考完了|考试(?:已经)?结束了|取消.{0,12}考试|不考了|面试完了|项目完成|已经解决|done|finished|completed", text) and self._resolved_for(item, text):
                self.store.update_scheduled_status(item.id, "cancelled")
                return False, "topic already resolved"

        sent = [entry for entry in self.store.list_scheduled_messages("sent", limit=None)
                if entry.id != item.id and not entry.topic.startswith(("reminder:", "reply:", "custom:"))]
        if any(entry.topic == item.topic and entry.conversation_id == item.conversation_id and entry.updated_at >= item.created_at for entry in sent):
            self.store.update_scheduled_status(item.id, "cancelled")
            return False, "duplicate topic already sent"
        sent_today = [
            entry for entry in sent
            if datetime.fromisoformat(entry.updated_at).astimezone(zone).date() == current.date()
        ]
        if len(sent_today) >= self.settings.max_per_day:
            return False, "daily limit"
        minimum = timedelta(hours=self.settings.minimum_interval_hours)
        if any(current - datetime.fromisoformat(entry.updated_at).astimezone(zone) < minimum for entry in sent):
            return False, "minimum interval"
        return True, "still relevant"

    def _candidate(self, message: Message) -> ScheduledMessage | None:
        text = message.content
        zone = timezone(timedelta(minutes=self.store.utc_offset_minutes))
        now = datetime.now().astimezone(zone)
        if re.search(r"不要.{0,6}提醒|别.{0,6}提醒|不用.{0,6}提醒|^\s*取消", text):
            return None
        reminder = self._explicit_reminder(message, now)
        if reminder:
            return reminder
        topic = intent = reason = None
        importance = 0.0
        preferred: datetime | None = None
        if re.search(r"明天.{0,12}(面试|答辩)|(?:面试|答辩).{0,12}明天", text):
            topic = "interview"
            intent = "ask how the interview or presentation went"
            reason = "user mentioned an important interview tomorrow"
            importance = 0.80
            preferred = (now + timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
        if not topic or not preferred:
            return None
        preferred = self._outside_quiet_hours(preferred)
        return ScheduledMessage(
            id=f"sched_{uuid.uuid4().hex}", conversation_id=message.conversation_id,
            created_at=utc_now(), scheduled_at=preferred.isoformat(),
            earliest_at=(preferred - timedelta(hours=1)).isoformat(),
            latest_at=(preferred + timedelta(hours=18)).isoformat(), topic=topic,
            draft_intent=intent, source_memory_ids=[message.id], reason=reason,
            importance=importance,
        )

    def _allowed(self, candidate: ScheduledMessage) -> bool:
        pending = self.store.list_scheduled_messages("pending", limit=None)
        if any(item.conversation_id == candidate.conversation_id and item.topic == candidate.topic for item in pending):
            return False
        if candidate.topic.startswith("reminder:"):
            return True
        zone = timezone(timedelta(minutes=self.store.utc_offset_minutes))
        candidate_day = datetime.fromisoformat(candidate.scheduled_at).astimezone(zone).date()
        active = [item for item in self.store.list_scheduled_messages(limit=None)
                  if item.status in {"pending", "sent"} and not item.topic.startswith(("reminder:", "reply:", "custom:"))]
        same_day = [item for item in active
                    if item.status in {"pending", "sent"}
                    and datetime.fromisoformat(item.scheduled_at).astimezone(zone).date() == candidate_day]
        if len(same_day) >= self.settings.max_per_day:
            return False
        scheduled_at = datetime.fromisoformat(candidate.scheduled_at)
        minimum = timedelta(hours=self.settings.minimum_interval_hours)
        return not any(abs(scheduled_at - datetime.fromisoformat(item.scheduled_at)) < minimum for item in active)

    def _explicit_reminder(self, message: Message, now: datetime):
        # Deliberately narrow grammar: ambiguous schedules are not guessed.
        clock = r"(?P<day>今天|明天|后天)\s*(?P<hour>\d{1,2})(?:[:：](?P<minute>\d{2})|点(?P<half>半)?(?:(?P<minute_cn>\d{1,2})分?)?)"
        text = message.content.strip().rstrip("。！!")
        match = re.fullmatch(clock + r"\s*提醒我\s*(?P<task>.+)", text) or re.fullmatch(r"提醒我\s*" + clock + r"\s*(?P<task>.+)", text)
        if not match:
            return None
        hour = int(match['hour'])
        minute = int(match['minute'] or match['minute_cn'] or (30 if match['half'] else 0))
        task = match['task'].strip()
        if hour > 23 or minute > 59 or not task or len(task) > 300:
            return None
        preferred = (now + timedelta(days={"今天": 0, "明天": 1, "后天": 2}[match['day']])).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if preferred <= now:
            return None
        shifted = self._outside_quiet_hours(preferred)
        topic = "reminder:" + hashlib.sha256((shifted.isoformat() + task).encode()).hexdigest()[:20]
        return ScheduledMessage(
            id=f"sched_{uuid.uuid4().hex}", conversation_id=message.conversation_id,
            created_at=utc_now(), scheduled_at=shifted.isoformat(), earliest_at=shifted.isoformat(),
            latest_at=(shifted + timedelta(hours=18)).isoformat(), topic=topic, draft_intent=task,
            source_memory_ids=[message.id], reason="explicit reminder" + ("; moved outside quiet hours" if shifted != preferred else ""), importance=1.0,
        )

    def _outside_quiet_hours(self, value: datetime) -> datetime:
        hour = value.hour
        if self._is_quiet_hour(hour):
            start, end = self.settings.quiet_start_hour, self.settings.quiet_end_hour
            value = value.replace(hour=end, minute=15, second=0, microsecond=0)
            if hour >= start and start > end:
                value += timedelta(days=1)
        return value

    def _is_quiet_hour(self, hour: int) -> bool:
        start, end = self.settings.quiet_start_hour, self.settings.quiet_end_hour
        if start == end:
            return False
        return hour >= start or hour < end if start > end else start <= hour < end

    @staticmethod
    def _topic_related(topic: str, text: str) -> bool:
        if topic.startswith("exam:"):
            return any(word in text for word in ("考试", "测验", "考完", "exam"))
        words = {"exam": ("考试", "测验", "exam"), "interview": ("面试", "答辩", "interview")}
        return any(word in text for word in words.get(topic, (topic,)))

    def _resolved_for(self, item: ScheduledMessage, text: str) -> bool:
        if item.topic.startswith("exam:"):
            subject = next((s for s in SUBJECTS if s in text), "")
            if subject:
                return "用户的" + subject + "考试" in item.draft_intent
            if not self._topic_related(item.topic, text):
                return False
            if re.search(r"(?:别|不用|不要).{0,8}(?:提醒|关心)|取消.*考试", text):
                return True
            pending_exams = [s for s in self.store.list_scheduled_messages('pending', limit=None)
                             if s.conversation_id == item.conversation_id and s.topic.startswith('exam:')]
            return len(pending_exams) == 1
        return self._topic_related(item.topic, text)
