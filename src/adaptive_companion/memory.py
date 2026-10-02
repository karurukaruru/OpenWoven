from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from .search_terms import term_occurrences
from .storage import SQLiteStore
from .archives import CalendarArchives
from .context import estimate_tokens


class MemoryManager:
    ROLLING_BATCH_SIZE = 256

    def __init__(
        self, store: SQLiteStore, message_threshold: int = 12,
        token_threshold: int = 5400, minimum_density: float = 0.12,
    ):
        self.store = store
        self.message_threshold = message_threshold
        self.token_threshold = token_threshold
        self.minimum_density = minimum_density
        self.archives = CalendarArchives(store, self._structured_summary)

    def maintain(self, now: datetime | None = None, limit: int = 64) -> dict:
        return self.archives.maintain(now, limit)

    def consolidate_monthly(self, month: str | None = None) -> dict[str, Any] | None:
        from .calendar_time import month_range
        target = datetime.fromisoformat((month or self.store.local_today()[:7]) + '-01').date()
        start, end = month_range(target)
        self.maintain()
        self.archives.seal('monthly', start.isoformat(), end.isoformat())
        return next((a['content'] for a in self.archives.list('monthly', 200)
                     if a['period_start'] == start.isoformat()), None)

    def maybe_create_rolling_summary(self, conversation_id: str) -> dict[str, Any] | None:
        # All summary work is local. Keep its read/commit/cursor atomic with a
        # concurrent message deletion or observer commit.
        with self.store.connection():
            return self._create_rolling_summary(conversation_id)

    def _create_rolling_summary(self, conversation_id: str) -> dict[str, Any] | None:
        last_id = self.store.get_metadata(f"rolling_last:{conversation_id}")
        # Consume a contiguous, bounded prefix. One failed learning attempt or
        # a lifetime of low-density chat must not grow every maintenance read.
        messages = self.store.list_messages_after(conversation_id, last_id, limit=self.ROLLING_BATCH_SIZE)
        full_batch = len(messages) == self.ROLLING_BATCH_SIZE
        for index, message in enumerate(messages):
            if message.role == 'user' and message.learning_status in {'pending', 'processing'}:
                messages = messages[:index]
                full_batch = False
                break
        if not messages:
            return None
        token_count = sum(estimate_tokens(m.content) for m in messages)
        if not full_batch and len(messages) < self.message_threshold and token_count < self.token_threshold:
            return None
        user_messages = [m for m in messages if m.role == "user"]
        # Failed extraction is not learned evidence. Retain its raw input and
        # provenance, mark the incomplete archive, and let subsequent turns seal.
        evidence = self.store.evidence_for_sources([m.id for m in user_messages if m.learning_status != 'failed'])
        informative = [m for m in user_messages if len(m.content.strip()) >= 8]
        density = (len(evidence) + len(informative) * 0.25) / max(1, len(user_messages))
        if density < self.minimum_density and not full_batch:
            return None

        content = self._structured_summary(messages, evidence)
        if any(m.learning_status == 'failed' for m in user_messages):
            content['learning_incomplete'] = True
        if density < self.minimum_density:
            content['low_information'] = True
        tags = self._top_tags(" ".join(m.content for m in user_messages))
        period = f"{conversation_id}:{messages[0].id}:{messages[-1].id}"
        memory_id = self.store.upsert_memory(
            "rolling", period, content, messages[0].id, messages[-1].id,
            tags, importance=0.65, confidence=0.85,
            source_message_ids=[m.id for m in messages],
        )
        if not memory_id:
            return None
        self.store.set_metadata(f"rolling_last:{conversation_id}", messages[-1].id)
        return content

    def consolidate_daily(self, date: str | None = None, min_information: int = 1) -> dict[str, Any] | None:
        target = date or self.store.local_today()
        if target < self.store.local_today():
            self.archives.seal('daily', target, target)
            return next((a['content'] for a in self.archives.list('daily', 200)
                         if a['period_start'] == target), None)
        with self.store.connection() as conn:
            message_rows = conn.execute(
                "SELECT m.* FROM messages m JOIN message_calendar c ON c.message_id=m.id WHERE c.local_day=? ORDER BY m.timestamp,m.rowid", (target,)
            ).fetchall()
            evidence_rows = conn.execute(
                """SELECT e.* FROM evidence e JOIN messages m ON m.id=e.source_message_id
                JOIN message_calendar c ON c.message_id=m.id
                WHERE c.local_day=? ORDER BY m.timestamp,m.rowid""", (target,)
            ).fetchall()
        if not message_rows:
            return None
        evidence = [self.store._evidence_from_row(row) for row in evidence_rows]
        important = [e for e in evidence if e.importance >= 0.6]
        if len(important) < min_information:
            return None
        content = {
            "date": target,
            "important_events": [e.value for e in important if e.type == "event"],
            "user_updates": [f"{e.key}: {e.value}" for e in important if e.type == "profile_fact"],
            "new_preferences": [self._evidence_phrase(e) for e in important if e.type in {
                "preference", "dislike", "interaction_preference"}],
            "active_projects": self._ongoing_goals(evidence),
            "emotional_context": [e.value for e in important if e.key == "current.mood"],
            "unresolved_topics": [],
        }
        tags = self._top_tags(" ".join(row["content"] for row in message_rows))
        memory_id = self.store.upsert_memory(
            "daily", target, content, message_rows[0]["id"], message_rows[-1]["id"],
            tags, importance=0.75, confidence=0.88,
            source_message_ids=[row["id"] for row in message_rows],
        )
        return content if memory_id else None

    def consolidate_weekly(self, week_end: str | None = None) -> dict[str, Any] | None:
        end = datetime.fromisoformat(week_end).date() if week_end else datetime.fromisoformat(self.store.local_today()).date()
        start = end - timedelta(days=6)
        daily = [m for m in self.store.list_memories("daily", limit=100)
                 if m["period_key"] and start.isoformat() <= m["period_key"] <= end.isoformat()]
        with self.store.connection() as conn:
            source_rows = conn.execute(
                "SELECT m.id FROM messages m JOIN message_calendar c ON c.message_id=m.id WHERE c.local_day BETWEEN ? AND ?",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
            rows = conn.execute(
                """SELECT e.* FROM evidence e JOIN messages m ON m.id=e.source_message_id
                JOIN message_calendar c ON c.message_id=m.id
                WHERE c.local_day BETWEEN ? AND ? ORDER BY m.timestamp,m.rowid""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        evidence = [self.store._evidence_from_row(row) for row in rows]
        if not daily and not evidence:
            return None

        preference_counts = Counter(
            self._evidence_phrase(e) for e in evidence
            if e.type in {"preference", "dislike", "interaction_preference"}
        )
        completed = [e.value for e in evidence if e.type == "event" and any(
            word in str(e.value) for word in ("完成", "结束", "通过", "done", "finished"))]
        goals = self._ongoing_goals(evidence)
        content = {
            "week": f"{start.isoformat()}..{end.isoformat()}",
            "long_term_trends": [item for item, count in preference_counts.items() if count >= 2],
            "stable_preferences": list(preference_counts.keys()),
            "merged_facts": self._unique([e.value for e in evidence if e.type == "profile_fact"]),
            "archived_events": self._unique(completed),
            "continuing_goals": self._unique(goals),
            "relationship_updates": [f"{len(evidence)} evidence items observed this week"],
        }
        period = f"{start.isoformat()}..{end.isoformat()}"
        existing = next((a for a in self.archives.list('weekly', 200) if a['period_start'] == start.isoformat() and a['period_end'] == end.isoformat()), None)
        if existing:
            return existing['content']
        source_start = daily[-1]["source_start_id"] if daily else (evidence[0].source_message_id if evidence else None)
        source_end = daily[0]["source_end_id"] if daily else (evidence[-1].source_message_id if evidence else None)
        tags = self._top_tags(" ".join(str(e.value) for e in evidence))
        memory_id = self.store.upsert_memory(
            "weekly", period, content, source_start, source_end, tags,
            importance=0.85, confidence=0.86,
            source_message_ids=[row["id"] for row in source_rows],
        )
        return content if memory_id else None

    @staticmethod
    def _structured_summary(messages, evidence) -> dict[str, Any]:
        return {
            "important_events": [e.value for e in evidence if e.type == "event"],
            "new_user_facts": [f"{e.key}: {e.value}" for e in evidence if e.type == "profile_fact"],
            "active_topics": MemoryManager._top_tags(" ".join(m.content for m in messages if m.role == "user")),
            "user_goals": MemoryManager._ongoing_goals(evidence),
            "unresolved_topics": [],
            "interaction_changes": [MemoryManager._evidence_phrase(e) for e in evidence
                                    if e.type == "interaction_preference"],
            "emotional_context": [e.value for e in evidence if e.key == "current.mood"],
        }

    @staticmethod
    def _ongoing_goals(evidence) -> list[Any]:
        # Replay current-goal transitions, not just the original announcements.
        # This matches the MVP's one-active-goal AUL; it is not a multi-project
        # lifecycle tracker. Completed events remain in their historical fields.
        goals = []
        for item in evidence:
            if item.key == "current.current_goal":
                goals = [item.value] if item.value is not None else []
            elif item.type == "goal" and item.value is not None and item.value not in goals:
                goals.append(item.value)
        return goals

    @staticmethod
    def _top_tags(text: str, limit: int = 8) -> list[str]:
        stop = {"这个", "那个", "我们", "你们", "什么", "现在", "最近", "然后", "就是", "其实",
                "嗯", "嗯嗯", "哦", "好", "好的", "哈哈", "呵呵", "啊", "the", "and", "that", "this",
                "okay", "thanks", "です", "ます", "した", "する", "これ", "それ", "そう", "はい", "うん"}
        counts = Counter(t for t in term_occurrences(text) if t not in stop and not t.isdigit())
        # Counter preserves first occurrence on ties, not randomized set order.
        return [term for term, _ in counts.most_common(limit)]

    @staticmethod
    def _evidence_phrase(evidence) -> str:
        if evidence.direction:
            return f"{evidence.key} {evidence.direction}"
        return f"{evidence.key}: {evidence.value}"

    @staticmethod
    def _unique(values: list[Any]) -> list[Any]:
        result = []
        for value in values:
            if value is not None and value not in result:
                result.append(value)
        return result
