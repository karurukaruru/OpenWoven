"""Durable user-requested replies, separate from unsolicited proactive quotas."""
from __future__ import annotations

import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta

from .models import Message, ScheduledMessage, utc_now
from .storage import SQLiteStore
from .turns import composer_gate


class DelayedReplies:
    def __init__(self, store: SQLiteStore, idle_seconds: int = 20):
        self.store = store
        self.idle_seconds = max(10, min(60, idle_seconds))

    def enqueue_turn(self, message: Message, greeting_seconds: int = 0, connection=None) -> ScheduledMessage:
        # Superseding the old task and saving the replacement are one commit.
        with (nullcontext(connection) if connection is not None else self.store.connection()) as conn:
            if connection is None:
                conn.execute('BEGIN IMMEDIATE')
            sources = []
            rows = conn.execute("SELECT * FROM scheduled_messages WHERE status='pending' ORDER BY scheduled_at").fetchall()
            for old in (self.store._scheduled_from_row(row) for row in rows):
                if old.conversation_id == message.conversation_id and old.topic.startswith('reply:'):
                    sources.extend(old.source_memory_ids)
                    conn.execute("UPDATE scheduled_messages SET status='cancelled',updated_at=? WHERE id=?", (utc_now(), old.id))
            sources = list(dict.fromkeys(sources + [message.id]))
            messages = {key: conn.execute('SELECT content FROM messages WHERE id=?', (key,)).fetchone() for key in sources}
            sources = [key for key in sources if messages[key]]
            due = datetime.now().astimezone() + timedelta(seconds=max(self.idle_seconds, greeting_seconds if len(sources) == 1 else 0))
            item = ScheduledMessage(id=f'sched_{uuid.uuid4().hex}', conversation_id=message.conversation_id,
                created_at=utc_now(), scheduled_at=due.isoformat(), earliest_at=due.isoformat(),
                latest_at=(due + timedelta(days=1)).isoformat(), topic='reply:' + message.id,
                draft_intent='\n'.join(messages[key]['content'] for key in sources), source_memory_ids=sources,
                reason='batched user turn; wait until composer is empty and idle', importance=1.0)
            self.store.save_scheduled_message(item, connection=conn)
            if connection is None:
                conn.commit()
        return item

    def enqueue(self, message: Message, seconds: int) -> ScheduledMessage:
        due = datetime.now().astimezone() + timedelta(seconds=seconds)
        item = ScheduledMessage(
            id=f"sched_{uuid.uuid4().hex}", conversation_id=message.conversation_id,
            created_at=utc_now(), scheduled_at=due.isoformat(), earliest_at=due.isoformat(),
            latest_at=(due + timedelta(minutes=30)).isoformat(), topic="reply:" + message.id,
            draft_intent=message.content, source_memory_ids=[message.id],
            reason="user-requested greeting reply; not an unsolicited check-in", importance=1.0,
        )
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self.store.save_scheduled_message(item, connection=conn)
            conn.execute("UPDATE messages SET status='waiting',error=NULL WHERE id=?", (message.id,))
            conn.commit()
        return item

    def cancel_for_conversation(self, conversation_id: str) -> None:
        # New content supersedes an unanswered greeting: never append an old "在".
        for item in self.store.list_scheduled_messages("pending", limit=None):
            if item.conversation_id == conversation_id and item.topic.startswith("reply:"):
                self.store.update_scheduled_status(item.id, "cancelled")
                self.store.update_message_status(item.topic[6:], "sent")

    def cancel_for_source(self, source_id: str) -> None:
        for item in self.store.list_scheduled_messages("pending", limit=None):
            if item.topic.startswith('reply:') and source_id in item.source_memory_ids:
                self.store.update_scheduled_status(item.id, "cancelled")
                for key in item.source_memory_ids:
                    if key != source_id:
                        self.store.update_message_status(key, 'failed', 'Turn stopped; retry the latest message')

    def revalidate(self, item_id: str) -> tuple[bool, str]:
        item = self.store.get_scheduled_message(item_id)
        if not item or item.status != "pending":
            return False, "not pending"
        source = self.store.get_message(item.topic[6:])
        if not source or source.status not in {"waiting", "failed"}:
            self.store.update_scheduled_status(item.id, "cancelled")
            return False, "source no longer waiting"
        if datetime.now().astimezone() > datetime.fromisoformat(item.latest_at):
            self.store.update_scheduled_status(item.id, "expired")
            for key in item.source_memory_ids:
                self.store.update_message_status(key, "failed", "Delayed reply expired; tap Retry for an immediate reply")
            return False, "expired"
        if item.reason.startswith('batched user turn'):
            if not composer_gate.idle(item.conversation_id, self.idle_seconds):
                return False, 'composer active'
        return True, "still waiting"
