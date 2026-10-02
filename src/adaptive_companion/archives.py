"""Rebuildable calendar archives. Every level retains raw-message provenance."""
from __future__ import annotations

import json
from datetime import date, datetime

from .models import Message, utc_now


class CalendarArchives:
    def __init__(self, store, summarize):
        self.store, self.summarize = store, summarize

    def maintain(self, now: datetime | None = None, limit: int = 64) -> dict:
        today = self.store.local_today(now)
        counts = dict(daily=0, weekly=0, monthly=0)
        with self.store.connection() as conn:
            pending = conn.execute(
                """SELECT * FROM archive_dirty WHERE period_end < ?
                ORDER BY CASE kind WHEN 'daily' THEN 0 WHEN 'weekly' THEN 1 ELSE 2 END,
                period_start LIMIT ?""", (today, max(1, min(256, limit))),
            ).fetchall()
        for item in pending:
            if self.seal(item['kind'], item['period_start'], item['period_end'], today):
                counts[item['kind']] += 1
        with self.store.connection() as conn:
            remaining = conn.execute('SELECT COUNT(*) FROM archive_dirty WHERE period_end < ?', (today,)).fetchone()[0]
        return {**counts, 'remaining': remaining, 'today': today}

    def seal(self, kind: str, start: str, end: str, today: str | None = None):
        if kind not in {'daily', 'weekly', 'monthly'}:
            raise ValueError('unknown archive kind')
        date.fromisoformat(start)
        date.fromisoformat(end)
        if start > end or end >= (today or self.store.local_today()):
            return False
        with self.store.connection() as conn:
            rows = conn.execute(
                """SELECT m.* FROM messages m JOIN message_calendar c ON c.message_id=m.id
                WHERE c.local_day BETWEEN ? AND ? AND m.role IN ('user','assistant')
                ORDER BY m.timestamp,m.rowid""", (start, end),
            ).fetchall()
            if any(r['role'] == 'user' and r['learning_status'] in {'pending','processing'} for r in rows):
                return False
            if kind != 'daily' and conn.execute(
                "SELECT 1 FROM archive_dirty WHERE kind='daily' AND period_start BETWEEN ? AND ? LIMIT 1", (start, end),
            ).fetchone():
                return False
            if not rows:
                conn.execute('DELETE FROM archive_dirty WHERE kind=? AND period_start=? AND period_end=?', (kind, start, end))
                conn.commit()
                return True
            messages = [Message(**dict(r)) for r in rows]
            evidence = self.store.evidence_for_sources([m.id for m in messages if m.role == 'user'])
            summary = self.summarize(messages, evidence)
            users = [m for m in messages if m.role == 'user']
            sources = {e.source_message_id for e in evidence}
            salient = sorted(users, key=lambda m: (m.id in sources, len(m.content.strip()) >= 12,
                                                  min(240, len(m.content)), m.timestamp), reverse=True)
            highlights, seen = [], set()
            for m in salient:
                if m.content.strip() and m.content not in seen:
                    seen.add(m.content)
                    highlights.append({'message_id': m.id, 'text': m.content[:280], 'timestamp': m.timestamp})
                if len(highlights) >= (8 if kind == 'daily' else 6):
                    break
            summary = {k: self._unique(v)[:12] if isinstance(v, list) else v for k, v in summary.items()}
            summary.update(period_start=start, period_end=end, headline=start if start == end else f'{start} 至 {end}',
                           highlights=highlights, learning_incomplete=any(m.learning_status == 'failed' for m in users),
                           summary_method='local structured evidence + quotations; no model call')
            key = start if kind == 'daily' else start[:7] if kind == 'monthly' else f'{start}..{end}'
            memory_id = self.store.upsert_memory(
                kind, key, summary, messages[0].id, messages[-1].id, summary.get('active_topics', [])[:8],
                importance=0.78 if kind == 'daily' else 0.86, confidence=0.85,
                source_message_ids=[m.id for m in messages],
            )
            if not memory_id:
                return False
            conn.execute(
                """INSERT INTO archive_periods VALUES(?,?,?,?,?,?)
                ON CONFLICT(memory_id) DO UPDATE SET sealed_at=excluded.sealed_at,message_count=excluded.message_count""",
                (memory_id, kind, start, end, utc_now(), len(messages)),
            )
            conn.execute('DELETE FROM memory_links WHERE parent_id=?', (memory_id,))
            if kind != 'daily':
                kinds = ['daily'] if kind == 'weekly' else ['daily', 'weekly']
                marks = ','.join('?' for _ in kinds)
                children = conn.execute(f'SELECT memory_id FROM archive_periods WHERE kind IN ({marks}) AND period_start>=? AND period_end<=?',
                                        [*kinds, start, end]).fetchall()
                conn.executemany('INSERT OR IGNORE INTO memory_links VALUES(?,?)', [(memory_id, c['memory_id']) for c in children])
            if kind == 'weekly':
                conn.execute("INSERT OR IGNORE INTO memory_links SELECT memory_id,? FROM archive_periods WHERE kind='monthly' AND period_start<=? AND period_end>=?",
                             (memory_id, start, end))
            conn.execute('DELETE FROM archive_dirty WHERE kind=? AND period_start=? AND period_end=?', (kind, start, end))
            conn.commit()
            return True

    def list(self, kind='daily', limit=50):
        with self.store.connection() as conn:
            rows = conn.execute('SELECT a.*,m.content_json FROM archive_periods a JOIN memories m ON m.id=a.memory_id WHERE a.kind=? ORDER BY a.period_start DESC LIMIT ?',
                                (kind, max(1, min(200, limit)))).fetchall()
        return [{**{k: r[k] for k in r.keys() if k != 'content_json'}, 'content': json.loads(r['content_json'])} for r in rows]

    def detail(self, memory_id, offset=0, limit=50):
        with self.store.connection() as conn:
            row = conn.execute('SELECT a.*,m.content_json FROM archive_periods a JOIN memories m ON m.id=a.memory_id WHERE a.memory_id=?', (memory_id,)).fetchone()
            if not row:
                return None
            children = conn.execute('SELECT a.* FROM memory_links l JOIN archive_periods a ON a.memory_id=l.child_id WHERE l.parent_id=? ORDER BY a.kind DESC,a.period_start',
                                    (memory_id,)).fetchall()
            messages = conn.execute('''SELECT m.*,c.local_day,c.zone_name,c.utc_offset_minutes FROM memory_sources s
                JOIN messages m ON m.id=s.source_message_id JOIN message_calendar c ON c.message_id=m.id
                WHERE s.memory_id=? ORDER BY m.timestamp,m.rowid LIMIT ? OFFSET ?''',
                (memory_id, max(1, min(100, limit)), max(0, offset))).fetchall()
        return {**{k: row[k] for k in row.keys() if k != 'content_json'}, 'content': json.loads(row['content_json']),
                'children': [dict(c) for c in children], 'messages': [dict(m) for m in messages], 'offset': max(0, offset)}

    @staticmethod
    def _unique(values):
        seen, result = set(), []
        for value in values:
            key = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                result.append(value)
        return result
