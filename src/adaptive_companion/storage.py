from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from .models import Evidence, Message, ScheduledMessage, default_aul, utc_now
from .search_terms import terms, memory_text


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    token_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_time
ON messages(conversation_id, timestamp);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT,
    direction TEXT,
    strength REAL NOT NULL,
    confidence REAL NOT NULL,
    importance REAL NOT NULL,
    source_message_id TEXT NOT NULL REFERENCES messages(id),
    created_at TEXT NOT NULL,
    expires_at TEXT,
    signal TEXT NOT NULL,
    applied INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_evidence_key_time ON evidence(key, created_at);

CREATE TABLE IF NOT EXISTS aul_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    data_json TEXT NOT NULL,
    version INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value_json TEXT,
    new_value_json TEXT,
    reason TEXT NOT NULL,
    evidence_id TEXT,
    source_message_id TEXT,
    confidence REAL NOT NULL,
    aul_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('rolling', 'daily', 'weekly', 'long_term')),
    period_key TEXT,
    content_json TEXT NOT NULL,
    source_start_id TEXT,
    source_end_id TEXT,
    tags_json TEXT NOT NULL,
    importance REAL NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(kind, period_key)
);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

MIGRATION_1_TO_2 = """
ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'sent';
ALTER TABLE messages ADD COLUMN error TEXT;
ALTER TABLE messages ADD COLUMN reply_to_id TEXT;

CREATE TABLE scheduled_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    earliest_at TEXT NOT NULL,
    latest_at TEXT NOT NULL,
    topic TEXT NOT NULL,
    draft_intent TEXT NOT NULL,
    source_memory_ids_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    importance REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','cancelled','sent','expired')),
    sent_message_id TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_scheduled_status_time ON scheduled_messages(status, scheduled_at);
CREATE INDEX idx_scheduled_topic ON scheduled_messages(topic, status);

CREATE TABLE feedback (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id),
    kind TEXT NOT NULL,
    value_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_feedback_message ON feedback(message_id, created_at);
PRAGMA user_version=2;
"""

MIGRATION_2_TO_3 = """
ALTER TABLE messages ADD COLUMN learning_status TEXT NOT NULL DEFAULT 'not_applicable';
UPDATE messages SET learning_status='complete' WHERE role='user';
CREATE INDEX IF NOT EXISTS idx_messages_learning_status
ON messages(learning_status, timestamp);
PRAGMA user_version=3;
"""

MIGRATION_3_TO_4 = """
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
CREATE INDEX IF NOT EXISTS idx_evidence_applied_key ON evidence(applied, key);
PRAGMA user_version=4;
"""

MIGRATION_4_TO_5 = """
CREATE TABLE IF NOT EXISTS generation_metrics (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    source_id TEXT,
    result_message_id TEXT,
    provider TEXT NOT NULL,
    model TEXT,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_generation_metrics_time ON generation_metrics(created_at);
PRAGMA user_version=5;
"""

MIGRATION_5_TO_6 = """
CREATE TABLE IF NOT EXISTS memory_sources (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    source_message_id TEXT NOT NULL REFERENCES messages(id),
    PRIMARY KEY(memory_id, source_message_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_sources_message ON memory_sources(source_message_id);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_message_id);
PRAGMA user_version=6;
"""

MIGRATION_6_TO_7 = """
ALTER TABLE generation_metrics ADD COLUMN usage_source TEXT NOT NULL DEFAULT 'unknown';
PRAGMA user_version=7;
"""

MIGRATION_7_TO_8 = """
BEGIN IMMEDIATE;
CREATE TABLE memories_v8 (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('rolling','daily','weekly','monthly','long_term')),
    period_key TEXT, content_json TEXT NOT NULL, source_start_id TEXT, source_end_id TEXT,
    tags_json TEXT NOT NULL, importance REAL NOT NULL, confidence REAL NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(kind,period_key)
);
INSERT INTO memories_v8 SELECT * FROM memories;
CREATE TABLE memory_sources_v8 (
    memory_id TEXT NOT NULL REFERENCES memories_v8(id) ON DELETE CASCADE,
    source_message_id TEXT NOT NULL REFERENCES messages(id),
    PRIMARY KEY(memory_id,source_message_id)
);
INSERT INTO memory_sources_v8 SELECT * FROM memory_sources;
DROP TABLE memory_sources;
DROP TABLE memories;
ALTER TABLE memories_v8 RENAME TO memories;
ALTER TABLE memory_sources_v8 RENAME TO memory_sources;
CREATE INDEX idx_memory_sources_message ON memory_sources(source_message_id);
CREATE TABLE message_calendar (
    message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    local_day TEXT NOT NULL, utc_offset_minutes INTEGER NOT NULL, zone_name TEXT NOT NULL
);
CREATE INDEX idx_calendar_day ON message_calendar(local_day,message_id);
CREATE TABLE archive_periods (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    kind TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
    sealed_at TEXT NOT NULL, message_count INTEGER NOT NULL,
    UNIQUE(kind,period_start,period_end)
);
CREATE TABLE memory_links (
    parent_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    child_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    PRIMARY KEY(parent_id,child_id)
);
CREATE TABLE archive_dirty (
    kind TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
    PRIMARY KEY(kind,period_start,period_end)
);
CREATE TABLE search_documents (
    kind TEXT NOT NULL, source_id TEXT NOT NULL, term_count INTEGER NOT NULL,
    PRIMARY KEY(kind,source_id)
);
CREATE TABLE search_postings (
    kind TEXT NOT NULL, source_id TEXT NOT NULL, term TEXT NOT NULL,
    PRIMARY KEY(kind,source_id,term),
    FOREIGN KEY(kind,source_id) REFERENCES search_documents(kind,source_id) ON DELETE CASCADE
);
CREATE INDEX idx_search_term ON search_postings(term,kind,source_id);
CREATE TRIGGER search_delete_message AFTER DELETE ON messages BEGIN
    DELETE FROM search_documents WHERE kind='raw' AND source_id=OLD.id;
END;
CREATE TRIGGER search_delete_evidence AFTER DELETE ON evidence BEGIN
    DELETE FROM search_documents WHERE kind='evidence' AND source_id=OLD.id;
END;
CREATE TRIGGER search_delete_memory AFTER DELETE ON memories BEGIN
    DELETE FROM search_documents WHERE kind='memory' AND source_id=OLD.id;
END;
PRAGMA user_version=8;
COMMIT;
"""


MIGRATION_8_TO_9 = """
BEGIN IMMEDIATE;
CREATE TABLE message_delivery_plans (
    message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    plan_json TEXT NOT NULL
);
PRAGMA user_version=9;
COMMIT;
"""


MIGRATION_9_TO_10 = """
BEGIN IMMEDIATE;
CREATE TABLE notification_outbox (
    message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','submitted','foreground','disabled','expired')),
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_notification_outbox_pending ON notification_outbox(status,created_at);
PRAGMA user_version=10;
COMMIT;
"""


MIGRATION_10_TO_11 = """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS character_facts (
    character_id TEXT NOT NULL, path TEXT NOT NULL, value TEXT NOT NULL,
    source_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL, PRIMARY KEY(character_id,path)
);
CREATE INDEX IF NOT EXISTS idx_character_facts_source ON character_facts(source_message_id);
PRAGMA user_version=11;
COMMIT;
"""


def _dirty_sql(day: str) -> str:
    return f"""
    INSERT OR IGNORE INTO archive_dirty VALUES('daily',{day},{day});
    INSERT OR IGNORE INTO archive_dirty VALUES('weekly',date({day},'-6 days','weekday 1'),
        date({day},'-6 days','weekday 1','+6 days'));
    INSERT OR IGNORE INTO archive_dirty VALUES('monthly',date({day},'start of month'),
        date({day},'start of month','+1 month','-1 day'));
    """


ARCHIVE_TRIGGERS = "".join(
    f"CREATE TRIGGER IF NOT EXISTS calendar_{event.lower()} AFTER {event} ON message_calendar BEGIN "
    + _dirty_sql(f"{prefix}.local_day") + " END;"
    for event, prefix in (("INSERT", "NEW"), ("DELETE", "OLD"), ("UPDATE", "NEW"))
) + "".join(
    f"CREATE TRIGGER IF NOT EXISTS archive_evidence_{event.lower()} AFTER {event} ON evidence BEGIN "
    + _dirty_sql(f"(SELECT local_day FROM message_calendar WHERE message_id={prefix}.source_message_id)")
    + " END;"
    for event, prefix in (("INSERT", "NEW"), ("DELETE", "OLD"), ("UPDATE", "NEW"))
) + """
CREATE TRIGGER IF NOT EXISTS archive_learning_update AFTER UPDATE OF learning_status ON messages BEGIN
""" + _dirty_sql("(SELECT local_day FROM message_calendar WHERE message_id=NEW.id)") + " END;"


class SQLiteStore:
    """Small repository layer. A fresh connection per operation is thread-safe."""

    def __init__(self, path: str | Path, utc_offset_minutes: int | None = None, zone_name: str | None = None):
        self.path = str(path)
        offset = datetime.now().astimezone().utcoffset()
        self.utc_offset_minutes = utc_offset_minutes if utc_offset_minutes is not None else int(offset.total_seconds() // 60)
        if not isinstance(self.utc_offset_minutes, int) or abs(self.utc_offset_minutes) >= 1440:
            raise ValueError("memory UTC offset must be an integer within +/-1439 minutes")
        self.zone_name = zone_name or f"UTC{self.utc_offset_minutes / 60:+g}"
        self._memory_uri = f"file:companion_{uuid.uuid4().hex}?mode=memory&cache=shared"
        # Serialize this store instance's short SQLite transactions. Observer/model
        # work happens outside the lock, so dialogue is never held behind an LLM call.
        self._connection_lock = threading.RLock()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_connection: sqlite3.Connection | None = None
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        if self.path == ":memory:":
            if self._memory_connection is None:
                self._memory_connection = sqlite3.connect(
                    self._memory_uri,
                    uri=True,
                    check_same_thread=False,
                    timeout=30,
                )
                self._configure(self._memory_connection)
            conn = sqlite3.connect(
                self._memory_uri,
                uri=True,
                check_same_thread=False,
                timeout=30,
            )
        else:
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self._configure(conn)
        return conn

    def close(self) -> None:
        with self._connection_lock:
            if self._memory_connection is not None:
                self._memory_connection.close()
                self._memory_connection = None

    @staticmethod
    def _configure(conn: sqlite3.Connection) -> None:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with self._connection_lock:
            conn = self._connect()
            try:
                yield conn
            finally:
                conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version == 0:
                # Databases from the Core MVP predate version tracking but match v1.
                conn.execute("PRAGMA user_version=1")
                version = 1
            if version < 2:
                conn.executescript(MIGRATION_1_TO_2)
                version = 2
            if version < 3:
                conn.executescript(MIGRATION_2_TO_3)
                version = 3
            if version < 4:
                conn.executescript(MIGRATION_3_TO_4)
                version = 4
            if version < 5:
                conn.executescript(MIGRATION_4_TO_5)
                version = 5
            if version < 6:
                conn.executescript(MIGRATION_5_TO_6)
                version = 6
            if version < 7:
                conn.executescript(MIGRATION_6_TO_7)
                version = 7
            if version < 8:
                conn.executescript(MIGRATION_7_TO_8)
                version = 8
            if version < 9:
                conn.executescript(MIGRATION_8_TO_9)
                version = 9
            if version < 10:
                conn.executescript(MIGRATION_9_TO_10)
                version = 10
            if version < 11:
                conn.executescript(MIGRATION_10_TO_11)
            # Additive index, no schema/data migration. Run after reply_to_id is
            # added so both fresh and legacy databases can use batched lookup.
            conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_reply_to ON messages(reply_to_id)')
            # SQLite appends rowid to this index, so bounded rolling prefixes
            # seek by conversation/insertion order without sorting all history.
            conn.execute('CREATE INDEX IF NOT EXISTS idx_messages_conversation_sequence ON messages(conversation_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_scheduled_sent ON scheduled_messages(sent_message_id)')
            conn.executescript(ARCHIVE_TRIGGERS)
            now = utc_now()
            conn.execute(
                "INSERT OR IGNORE INTO aul_state(singleton,data_json,version,updated_at) VALUES(1,?,?,?)",
                (json.dumps(default_aul(), ensure_ascii=False), 0, now),
            )
            conn.commit()
            self._backfill_calendar_and_search(conn)

    def _write_calendar(self, conn, message_id: str, timestamp: str) -> None:
        instant = datetime.fromisoformat(timestamp)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        local_day = instant.astimezone(timezone(timedelta(minutes=self.utc_offset_minutes))).date().isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO message_calendar VALUES(?,?,?,?)",
            (message_id, local_day, self.utc_offset_minutes, self.zone_name),
        )

    def local_today(self, now: datetime | None = None) -> str:
        value = now or datetime.now(timezone.utc)
        return value.astimezone(timezone(timedelta(minutes=self.utc_offset_minutes))).date().isoformat()

    @staticmethod
    def _index(conn, kind: str, source_id: str, text: str) -> None:
        tokens = sorted(terms(text))
        conn.execute("DELETE FROM search_documents WHERE kind=? AND source_id=?", (kind, source_id))
        conn.execute("INSERT INTO search_documents VALUES(?,?,?)", (kind, source_id, len(tokens)))
        conn.executemany("INSERT INTO search_postings VALUES(?,?,?)", [(kind, source_id, t) for t in tokens])

    def _backfill_calendar_and_search(self, conn):
        batch_size = 256
        while rows := conn.execute("""SELECT id,timestamp FROM messages
            WHERE id NOT IN (SELECT message_id FROM message_calendar) LIMIT ?""", (batch_size,)).fetchall():
            for row in rows:
                self._write_calendar(conn, row['id'], row['timestamp'])
            conn.commit()
        version = conn.execute("SELECT value FROM metadata WHERE key='search_tokenizer_version'").fetchone()
        upgrade = not version or version[0] != '2'
        for kind, table in (("raw", "messages"), ("evidence", "evidence"), ("memory", "memories")):
            cursor_key = f'search_tokenizer_v2_cursor:{kind}'
            cursor_row = conn.execute('SELECT value FROM metadata WHERE key=?', (cursor_key,)).fetchone()
            cursor = int(cursor_row[0]) if cursor_row and upgrade else 0
            while True:
                if upgrade:
                    rows = conn.execute(f'''SELECT rowid AS search_rowid,* FROM {table}
                        WHERE rowid>? ORDER BY rowid LIMIT ?''', (cursor, batch_size)).fetchall()
                else:
                    role_filter = " AND role!='system'" if kind == 'raw' else ''
                    rows = conn.execute(f'''SELECT * FROM {table}
                        WHERE id NOT IN (SELECT source_id FROM search_documents WHERE kind=?)
                        {role_filter} LIMIT ?''', (kind, batch_size)).fetchall()
                if not rows:
                    break
                for row in rows:
                    if kind == 'raw':
                        if row['role'] == 'system':
                            continue
                        text = row['content']
                    elif kind == 'evidence':
                        text = row['key'] + ': ' + str(json.loads(row['value_json']))
                    else:
                        text = memory_text(json.loads(row['content_json']))
                    self._index(conn, kind, row['id'], text)
                if upgrade:
                    cursor = rows[-1]['search_rowid']
                    conn.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)', (cursor_key, str(cursor)))
                # Persist each bounded batch with its cursor. A process stop
                # resumes instead of restarting the lifetime index upgrade.
                conn.commit()
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('search_tokenizer_version','2')")
        conn.execute("DELETE FROM metadata WHERE key LIKE 'search_tokenizer_v2_cursor:%'")
        conn.commit()

    def save_message(
        self, conversation_id: str, role: str, content: str, status: str = "sent",
        error: str | None = None, reply_to_id: str | None = None,
        learning_status: str | None = None,
        timestamp: str | None = None,
        message_id: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> Message:
        if message_id is not None and (not isinstance(message_id, str) or not message_id.strip() or len(message_id) > 128):
            raise ValueError('message ID must be a nonempty string of at most 128 characters')
        message = Message(
            id=message_id if message_id is not None else f"msg_{uuid.uuid4().hex}",
            conversation_id=conversation_id,
            role=role,
            content=content,
            timestamp=timestamp or utc_now(),
            token_count=max(1, (len(content) + 3) // 4),
            status=status,
            error=error,
            reply_to_id=reply_to_id,
            learning_status=learning_status or ("pending" if role == "user" else "not_applicable"),
        )
        with (nullcontext(connection) if connection is not None else self.connection()) as conn:
            conn.execute(
                """INSERT INTO messages
                (id,conversation_id,role,content,timestamp,token_count,status,error,reply_to_id,
                 learning_status) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (message.id, message.conversation_id, message.role, message.content,
                 message.timestamp, message.token_count, message.status, message.error,
                 message.reply_to_id, message.learning_status),
            )
            self._write_calendar(conn, message.id, message.timestamp)
            if role != "system":
                self._index(conn, "raw", message.id, content)
            if connection is None:
                conn.commit()
        return message

    def get_message(self, message_id: str) -> Message | None:
        with self.connection() as conn:
            row = conn.execute(
                """SELECT id,conversation_id,role,content,timestamp,token_count,
                status,error,reply_to_id,learning_status FROM messages WHERE id=?""", (message_id,)
            ).fetchone()
        return Message(**dict(row)) if row else None

    def list_messages(
        self, conversation_id: str | None = None, limit: int | None = None,
        role: str | None = None,
    ) -> list[Message]:
        clauses, params = [], []
        if conversation_id:
            clauses.append("conversation_id=?")
            params.append(conversation_id)
        if role:
            clauses.append("role=?")
            params.append(role)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = " LIMIT ?" if limit else ""
        if limit:
            params.append(limit)
        query = f"""SELECT id,conversation_id,role,content,timestamp,token_count,
        status,error,reply_to_id,learning_status FROM messages{where}
        ORDER BY timestamp DESC, rowid DESC{limit_sql}"""
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [Message(**dict(row)) for row in reversed(rows)]

    def list_messages_after(self, conversation_id: str, after_id: str | None, limit: int | None = None) -> list[Message]:
        """Insertion-ordered contiguous tail; optional prefix cap for maintenance."""
        limit_sql = ' LIMIT ?' if limit is not None else ''
        params = [conversation_id, after_id]
        if limit is not None:
            params.append(max(1, int(limit)))
        with self.connection() as conn:
            rows = conn.execute(
                f"""SELECT id,conversation_id,role,content,timestamp,token_count,
                status,error,reply_to_id,learning_status FROM messages
                WHERE conversation_id=? AND rowid > COALESCE(
                    (SELECT rowid FROM messages WHERE id=?), 0
                ) ORDER BY rowid{limit_sql}""",
                params,
            ).fetchall()
        return [Message(**dict(row)) for row in rows]

    def list_messages_before(self, message_id: str, limit: int = 12) -> list[Message]:
        """Retry history ends at the target turn, never at the latest turn."""
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT m.* FROM messages m JOIN messages target ON target.id=?
                WHERE m.conversation_id=target.conversation_id AND m.rowid < target.rowid
                ORDER BY m.rowid DESC LIMIT ?""", (message_id, limit),
            ).fetchall()
        return [Message(**dict(row)) for row in reversed(rows)]

    def count_messages(self, conversation_id: str | None = None, role: str | None = None) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if conversation_id:
            clauses.append("conversation_id=?")
            params.append(conversation_id)
        if role:
            clauses.append("role=?")
            params.append(role)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM messages{where}", params).fetchone()
        return int(row["n"])

    def update_message_status(self, message_id: str, status: str, error: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE messages SET status=?,error=? WHERE id=?", (status, error, message_id)
            )
            conn.commit()

    def recover_interrupted_messages(self) -> int:
        """Convert process-interrupted sends into retryable failures on startup."""
        with self.connection() as conn:
            cursor = conn.execute(
                """UPDATE messages SET status='failed',
                error='The previous request was interrupted. Tap Retry.'
                WHERE role='user' AND status='pending'"""
            )
            conn.commit()
            return int(cursor.rowcount)

    def update_turn_status(self, source_message_ids: list[str], status: str, error: str | None = None) -> None:
        """One status commit for all user bubbles in a failed batched request."""
        with self.connection() as conn:
            conn.executemany("UPDATE messages SET status=?,error=? WHERE id=? AND role='user'",
                             [(status, error, key) for key in dict.fromkeys(source_message_ids)])
            conn.commit()

    def complete_reply(self, user_message_id: str, content: str, delivery_plan: dict | None = None,
                       source_message_ids: list[str] | None = None, character_update: dict | None = None) -> Message:
        """Atomically mark a user send complete and persist its assistant reply."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute(
                "SELECT conversation_id FROM messages WHERE id=? AND role='user'",
                (user_message_id,),
            ).fetchone()
            if not user:
                conn.rollback()
                raise ValueError("reply target user message does not exist")
            assistant = Message(
                id=f"msg_{uuid.uuid4().hex}", conversation_id=user["conversation_id"],
                role="assistant", content=content, timestamp=utc_now(),
                token_count=max(1, (len(content) + 3) // 4),
                reply_to_id=user_message_id,
            )
            conn.executemany(
                "UPDATE messages SET status='sent',error=NULL WHERE id=? AND role='user' AND conversation_id=?",
                [(key, user['conversation_id']) for key in dict.fromkeys((source_message_ids or []) + [user_message_id])],
            )
            conn.execute(
                """INSERT INTO messages
                (id,conversation_id,role,content,timestamp,token_count,status,error,reply_to_id,
                 learning_status) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (assistant.id, assistant.conversation_id, assistant.role, assistant.content,
                 assistant.timestamp, assistant.token_count, assistant.status, assistant.error,
                 assistant.reply_to_id, assistant.learning_status),
            )
            self._write_calendar(conn, assistant.id, assistant.timestamp)
            self._write_delivery_plan(conn, assistant.id, delivery_plan)
            self._index(conn, "raw", assistant.id, content)
            from .character_book import CharacterBook
            CharacterBook.commit(conn, assistant.id, character_update)
            conn.commit()
        return assistant

    def complete_scheduled_delivery(self, item_id: str, content: str, reply_to_id: str | None = None,
                                    delivery_plan: dict | None = None, character_update: dict | None = None) -> Message:
        """Atomically persist a proactive reply and consume its schedule."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            item = conn.execute(
                "SELECT conversation_id,status,source_memory_ids_json FROM scheduled_messages WHERE id=?",
                (item_id,),
            ).fetchone()
            if not item or item["status"] != "pending":
                conn.rollback()
                raise ValueError("scheduled message is no longer pending")
            if reply_to_id and not conn.execute(
                "SELECT 1 FROM messages WHERE id=? AND role='user' AND status IN ('waiting','failed')",
                (reply_to_id,),
            ).fetchone():
                raise ValueError("delayed reply source is no longer waiting")
            assistant = Message(
                id=f"msg_{uuid.uuid4().hex}", conversation_id=item["conversation_id"],
                role="assistant", content=content, timestamp=utc_now(),
                token_count=max(1, (len(content) + 3) // 4),
                reply_to_id=reply_to_id,
            )
            conn.execute(
                """INSERT INTO messages
                (id,conversation_id,role,content,timestamp,token_count,status,error,reply_to_id,
                 learning_status) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (assistant.id, assistant.conversation_id, assistant.role, assistant.content,
                 assistant.timestamp, assistant.token_count, assistant.status, assistant.error,
                 assistant.reply_to_id, assistant.learning_status),
            )
            self._write_delivery_plan(conn, assistant.id, delivery_plan)
            conn.execute(
                """UPDATE scheduled_messages SET status='sent',sent_message_id=?,updated_at=?
                WHERE id=?""",
                (assistant.id, utc_now(), item_id),
            )
            self._write_calendar(conn, assistant.id, assistant.timestamp)
            self._index(conn, "raw", assistant.id, content)
            # Saving a scheduled reply and queuing its notification is one commit.
            # Android submits separately, so process death never needs a new reply.
            conn.execute("INSERT INTO notification_outbox(message_id,created_at,updated_at) VALUES(?,?,?)",
                         (assistant.id, assistant.timestamp, assistant.timestamp))
            if reply_to_id:
                conn.execute("UPDATE messages SET status='sent',error=NULL WHERE id=?", (reply_to_id,))
                for key in json.loads(item['source_memory_ids_json']):
                    conn.execute("UPDATE messages SET status='sent',error=NULL WHERE id=? AND role='user' AND status IN ('waiting','failed')", (key,))
            from .character_book import CharacterBook
            CharacterBook.commit(conn, assistant.id, character_update)
            conn.commit()
        return assistant

    def pending_notifications(self, limit: int = 20) -> list[dict[str, Any]]:
        """Bounded local outbox; never replay notifications older than a day."""
        now = utc_now()
        with self.connection() as conn:
            conn.execute("""UPDATE notification_outbox SET status='expired',updated_at=?
                WHERE status='pending' AND julianday(created_at)<julianday(?)-1""", (now, now))
            rows = conn.execute("""SELECT n.message_id,n.created_at,m.content AS text
                FROM notification_outbox n JOIN messages m ON m.id=n.message_id
                WHERE n.status='pending' ORDER BY n.created_at,n.message_id LIMIT ?""",
                (max(1, min(100, int(limit))),)).fetchall()
            conn.commit()
        return [dict(row) for row in rows]

    def finish_notification(self, message_id: str, status: str) -> bool:
        """'submitted' acknowledges an OS call, not display or user receipt."""
        if status not in {'submitted', 'foreground', 'disabled'}:
            raise ValueError('Invalid notification acknowledgement')
        with self.connection() as conn:
            changed = conn.execute("""UPDATE notification_outbox SET status=?,updated_at=?
                WHERE message_id=? AND status='pending'""", (status, utc_now(), message_id)).rowcount
            conn.commit()
        return bool(changed)

    def update_learning_status(self, message_id: str, status: str) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE messages SET learning_status=? WHERE id=?", (status, message_id))
            conn.commit()

    def list_messages_for_learning(self, limit: int | None = 50) -> list[Message]:
        with self.connection() as conn:
            limit_sql = " LIMIT ?" if limit is not None else ""
            rows = conn.execute(
                f"""SELECT id,conversation_id,role,content,timestamp,token_count,
                status,error,reply_to_id,learning_status FROM messages
                WHERE role='user' AND learning_status IN ('pending','processing','failed')
                ORDER BY timestamp,rowid{limit_sql}""",
                (limit,) if limit is not None else (),
            ).fetchall()
        return [Message(**dict(row)) for row in rows]

    def save_feedback(self, message_id: str, kind: str, value: Any = None) -> str:
        feedback_id = f"fb_{uuid.uuid4().hex}"
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO feedback VALUES(?,?,?,?,?)",
                (feedback_id, message_id, kind, json.dumps(value, ensure_ascii=False), utc_now()),
            )
            conn.commit()
        return feedback_id

    def find_feedback(self, message_id: str, kind: str) -> str | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT id FROM feedback WHERE message_id=? AND kind=? ORDER BY created_at LIMIT 1",
                (message_id, kind),
            ).fetchone()
        return row["id"] if row else None

    def list_feedback(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM feedback ORDER BY created_at DESC,rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["value"] = json.loads(item.pop("value_json"))
            result.append(item)
        return result

    def record_generation_metric(
        self, *, kind: str, source_id: str | None, result_message_id: str | None,
        provider: str, model: str | None, prompt_tokens: int, completion_tokens: int,
        latency_ms: int, status: str, error: str | None = None,
        usage_source: str = "estimated",
    ) -> str:
        metric_id = f"metric_{uuid.uuid4().hex}"
        prompt = max(0, int(prompt_tokens))
        completion = max(0, int(completion_tokens))
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO generation_metrics
                (id,kind,source_id,result_message_id,provider,model,prompt_tokens,
                 completion_tokens,total_tokens,latency_ms,status,error,created_at,usage_source)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (metric_id, kind, source_id, result_message_id, provider, model,
                 prompt, completion, prompt + completion, max(0, int(latency_ms)),
                 status, error[:500] if error else None, utc_now(), usage_source),
            )
            conn.commit()
        return metric_id

    def list_generation_metrics(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM generation_metrics ORDER BY created_at DESC,rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_scheduled_message(self, item: ScheduledMessage, connection: sqlite3.Connection | None = None) -> None:
        with (nullcontext(connection) if connection is not None else self.connection()) as conn:
            conn.execute(
                """INSERT INTO scheduled_messages
                (id,conversation_id,created_at,scheduled_at,earliest_at,latest_at,topic,
                 draft_intent,source_memory_ids_json,reason,importance,status,sent_message_id,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item.id, item.conversation_id, item.created_at, item.scheduled_at,
                 item.earliest_at, item.latest_at, item.topic, item.draft_intent,
                 json.dumps(item.source_memory_ids, ensure_ascii=False), item.reason,
                 item.importance, item.status, item.sent_message_id, item.updated_at),
            )
            if connection is None:
                conn.commit()

    def get_scheduled_message(self, item_id: str) -> ScheduledMessage | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM scheduled_messages WHERE id=?", (item_id,)).fetchone()
        return self._scheduled_from_row(row) if row else None

    def list_scheduled_messages(
        self, status: str | None = None, limit: int | None = 200,
    ) -> list[ScheduledMessage]:
        query = "SELECT * FROM scheduled_messages"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY scheduled_at ASC, rowid ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._scheduled_from_row(row) for row in rows]

    @staticmethod
    def _write_delivery_plan(conn, message_id: str, plan: dict | None) -> None:
        if plan is not None:
            conn.execute('INSERT INTO message_delivery_plans(message_id,plan_json) VALUES(?,?)',
                         (message_id, json.dumps(plan, ensure_ascii=False)))

    def reply_sources_for(self, message_ids: list[str]) -> dict[str, list[str]]:
        result = {}
        with self.connection() as conn:
            for start in range(0, len(message_ids), 400):
                chunk = message_ids[start:start + 400]
                placeholders = ','.join('?' for _ in chunk)
                rows = conn.execute(f"SELECT sent_message_id,source_memory_ids_json FROM scheduled_messages WHERE topic LIKE 'reply:%' AND sent_message_id IN ({placeholders})", chunk).fetchall()
                for row in rows:
                    values = json.loads(row['source_memory_ids_json'])
                    if values:
                        result[row['sent_message_id']] = values
        return result

    def delivery_plans_for(self, message_ids: list[str]) -> dict[str, dict]:
        if not message_ids:
            return {}
        result = {}
        with self.connection() as conn:
            for start in range(0, len(message_ids), 500):
                batch = message_ids[start:start + 500]
                marks = ','.join('?' for _ in batch)
                rows = conn.execute(f'SELECT * FROM message_delivery_plans WHERE message_id IN ({marks})', batch)
                for row in rows:
                    result[row['message_id']] = json.loads(row['plan_json'])
        return result

    def update_scheduled_status(
        self, item_id: str, status: str, sent_message_id: str | None = None,
    ) -> None:
        with self.connection() as conn:
            item = conn.execute("SELECT topic FROM scheduled_messages WHERE id=?", (item_id,)).fetchone()
            conn.execute(
                """UPDATE scheduled_messages SET status=?,sent_message_id=COALESCE(?,sent_message_id),
                updated_at=? WHERE id=?""",
                (status, sent_message_id, utc_now(), item_id),
            )
            if item and item['topic'].startswith('reply:') and status in {'cancelled', 'expired'}:
                conn.execute("UPDATE messages SET status='failed',error=? WHERE id=? AND status='waiting'",
                             ("Delayed reply stopped; tap Retry for an immediate reply", item['topic'][6:]))
            conn.commit()

    def delete_scheduled_message(self, item_id: str) -> None:
        self.update_scheduled_status(item_id, 'cancelled')
        with self.connection() as conn:
            conn.execute("DELETE FROM scheduled_messages WHERE id=?", (item_id,))
            conn.commit()

    @staticmethod
    def _scheduled_from_row(row: sqlite3.Row) -> ScheduledMessage:
        return ScheduledMessage(
            id=row["id"], conversation_id=row["conversation_id"],
            created_at=row["created_at"], scheduled_at=row["scheduled_at"],
            earliest_at=row["earliest_at"], latest_at=row["latest_at"],
            topic=row["topic"], draft_intent=row["draft_intent"],
            source_memory_ids=json.loads(row["source_memory_ids_json"]),
            reason=row["reason"], importance=row["importance"], status=row["status"],
            sent_message_id=row["sent_message_id"], updated_at=row["updated_at"],
        )

    def save_evidence(self, items: list[Evidence], connection: sqlite3.Connection | None = None) -> None:
        if not items:
            return
        with (nullcontext(connection) if connection is not None else self.connection()) as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO evidence
                (id,type,key,value_json,direction,strength,confidence,importance,
                 source_message_id,created_at,expires_at,signal,applied)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                [(
                    e.id, e.type, e.key, json.dumps(e.value, ensure_ascii=False), e.direction,
                    e.strength, e.confidence, e.importance, e.source_message_id,
                    e.created_at, e.expires_at, e.signal,
                ) for e in items],
            )
            for item in items:
                # INSERT OR IGNORE must not index the rejected duplicate's value.
                saved = conn.execute("SELECT key,value_json FROM evidence WHERE id=?", (item.id,)).fetchone()
                self._index(conn, "evidence", item.id, saved['key'] + ': ' + str(json.loads(saved['value_json'])))
            if connection is None:
                conn.commit()

    def replace_evidence_for_source(self, source_message_id: str, items: list[Evidence]) -> set[str]:
        """Idempotently replace observer output for one user message."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            affected = {
                row["key"] for row in conn.execute(
                    "SELECT DISTINCT key FROM evidence WHERE source_message_id=?",
                    (source_message_id,),
                ).fetchall()
            }
            conn.execute("DELETE FROM evidence WHERE source_message_id=?", (source_message_id,))
            exists = conn.execute("SELECT 1 FROM messages WHERE id=?", (source_message_id,)).fetchone()
            if exists and items:
                conn.executemany(
                    """INSERT INTO evidence
                    (id,type,key,value_json,direction,strength,confidence,importance,
                     source_message_id,created_at,expires_at,signal,applied)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                    [(
                        e.id, e.type, e.key, json.dumps(e.value, ensure_ascii=False), e.direction,
                        e.strength, e.confidence, e.importance, e.source_message_id,
                        e.created_at, e.expires_at, e.signal,
                    ) for e in items],
                )
                affected.update(item.key for item in items)
                for item in items:
                    self._index(conn, "evidence", item.id, item.key + ': ' + str(item.value))
            conn.commit()
        return affected

    @staticmethod
    def _evidence_from_row(row: sqlite3.Row) -> Evidence:
        return Evidence(
            id=row["id"], type=row["type"], key=row["key"],
            value=json.loads(row["value_json"]) if row["value_json"] is not None else None,
            direction=row["direction"], strength=row["strength"],
            confidence=row["confidence"], importance=row["importance"],
            source_message_id=row["source_message_id"], created_at=row["created_at"],
            expires_at=row["expires_at"], signal=row["signal"],
        )

    def list_evidence(self, key: str | None = None, limit: int = 200) -> list[Evidence]:
        query = "SELECT * FROM evidence"
        params: list[Any] = []
        if key:
            query += " WHERE key=?"
            params.append(key)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._evidence_from_row(row) for row in rows]

    def evidence_for_sources(self, source_ids: list[str]) -> list[Evidence]:
        """Read the exact summary inputs, without a global recent-evidence cap."""
        items = []
        with self.connection() as conn:
            for offset in range(0, len(source_ids), 400):
                batch = source_ids[offset:offset + 400]
                marks = ",".join("?" for _ in batch)
                rows = conn.execute(
                    f"""SELECT e.* FROM evidence e JOIN messages m ON m.id=e.source_message_id
                    WHERE e.source_message_id IN ({marks}) ORDER BY m.timestamp,m.rowid,e.rowid""",
                    batch,
                ).fetchall()
                items.extend(self._evidence_from_row(row) for row in rows)
        return items

    def get_aul(self) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT data_json,version,updated_at FROM aul_state WHERE singleton=1").fetchone()
        data = json.loads(row["data_json"])
        data["version"] = row["version"]
        data["updated_at"] = row["updated_at"]
        return data

    def list_audit(self, field: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM audit_log"
        params: list[Any] = []
        if field:
            query += " WHERE field=?"
            params.append(field)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["old_value"] = json.loads(item.pop("old_value_json"))
            item["new_value"] = json.loads(item.pop("new_value_json"))
            result.append(item)
        return result

    def set_interaction_preference(self, key: str, value: float, reason: str) -> dict[str, Any]:
        from .models import INTERACTION_KEYS
        if key not in INTERACTION_KEYS:
            raise ValueError(f"unknown interaction preference: {key}")
        value = round(max(0.0, min(1.0, float(value))), 4)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT data_json,version FROM aul_state WHERE singleton=1").fetchone()
            data = json.loads(row["data_json"])
            old = data["interaction"][key]["value"]
            version = int(row["version"]) + 1
            now = utc_now()
            data["interaction"][key].update({
                "value": value, "confidence": 1.0, "last_updated": now,
            })
            data["version"] = version
            data["updated_at"] = now
            conn.execute(
                "UPDATE aul_state SET data_json=?,version=?,updated_at=? WHERE singleton=1",
                (json.dumps(data, ensure_ascii=False), version, now),
            )
            conn.execute(
                """INSERT INTO audit_log
                (created_at,field,old_value_json,new_value_json,reason,evidence_id,
                 source_message_id,confidence,aul_version) VALUES(?,?,?,?,?,?,?,?,?)""",
                (now, f"interaction.{key}", json.dumps(old), json.dumps(value), reason,
                 None, None, 1.0, version),
            )
            conn.commit()
        return data

    def upsert_memory(
        self, kind: str, period_key: str | None, content: dict[str, Any],
        source_start_id: str | None, source_end_id: str | None,
        tags: list[str], importance: float = 0.6, confidence: float = 0.8,
        source_message_ids: list[str] | None = None,
    ) -> str | None:
        memory_id = f"mem_{uuid.uuid4().hex}"
        now = utc_now()
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if source_message_ids is not None:
                # An asynchronous delete may invalidate the summary's snapshot.
                # Never re-create a derived memory from already deleted inputs.
                sources = sorted(set(source_message_ids))
                for offset in range(0, len(sources), 400):
                    batch = sources[offset:offset + 400]
                    marks = ",".join("?" for _ in batch)
                    found = conn.execute(
                        f"SELECT COUNT(*) FROM messages WHERE id IN ({marks})", batch,
                    ).fetchone()[0]
                    if found != len(batch):
                        return None
            existing = conn.execute(
                "SELECT id FROM memories WHERE kind=? AND period_key IS ?", (kind, period_key)
            ).fetchone()
            if existing:
                memory_id = existing["id"]
                conn.execute(
                    """UPDATE memories SET content_json=?,source_start_id=?,source_end_id=?,
                    tags_json=?,importance=?,confidence=?,updated_at=? WHERE id=?""",
                    (json.dumps(content, ensure_ascii=False), source_start_id, source_end_id,
                     json.dumps(tags, ensure_ascii=False), importance, confidence, now, memory_id),
                )
            else:
                conn.execute(
                    "INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (memory_id, kind, period_key, json.dumps(content, ensure_ascii=False),
                     source_start_id, source_end_id, json.dumps(tags, ensure_ascii=False),
                    importance, confidence, now, now),
                )
            conn.execute("DELETE FROM memory_sources WHERE memory_id=?", (memory_id,))
            if source_message_ids:
                conn.executemany(
                    "INSERT INTO memory_sources(memory_id,source_message_id) VALUES(?,?)",
                    [(memory_id, source_id) for source_id in set(source_message_ids)],
                )
            self._index(conn, "memory", memory_id, memory_text(content))
            conn.commit()
        return memory_id

    def list_memories(self, kind: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM memories"
        params: list[Any] = []
        if kind:
            query += " WHERE kind=?"
            params.append(kind)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["content"] = json.loads(item.pop("content_json"))
            item["tags"] = json.loads(item.pop("tags_json"))
            result.append(item)
        return result

    def get_metadata(self, key: str) -> str | None:
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            conn.commit()

    def clear_user_data(self) -> None:
        """Privacy reset for an explicit user action; app settings live outside this DB."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for table in (
                "audit_log", "feedback", "generation_metrics", "evidence", "scheduled_messages",
                "memories", "messages", "metadata",
            ):
                conn.execute(f"DELETE FROM {table}")
            conn.execute("DELETE FROM archive_dirty")
            conn.execute("DELETE FROM search_documents")
            state = default_aul()
            now = utc_now()
            conn.execute(
                "UPDATE aul_state SET data_json=?,version=0,updated_at=? WHERE singleton=1",
                (json.dumps(state, ensure_ascii=False), now),
            )
            conn.commit()
