from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime

from .calendar_time import resolve_period
from .search_terms import terms, memory_text, normalized_search_text, normalized_search_offsets


class MemoryRetriever:
    """Indexed lifetime search, followed by date/provenance-aware ranking."""
    def __init__(self, store):
        self.store = store

    def retrieve(self, query: str, limit: int = 8, exclude_message_ids: set[str] | None = None):
        excluded = exclude_message_ids or set()
        today = self.store.local_today()
        with self.store.connection() as conn:
            first = None
            if all(word in query for word in ('第', '月', '周', '天')):
                first = conn.execute("SELECT MIN(c.local_day) FROM message_calendar c JOIN messages m ON m.id=c.message_id WHERE m.role='user'").fetchone()[0]
            period = resolve_period(query, date.fromisoformat(today), date.fromisoformat(first) if first else None)
            query_text = period[2] if period else query
            query_terms = terms(query_text) - {'记得','之前','什么','这个','那个','我们','the','and','what','remember','about'}
            if len(query_terms) > 96:
                normalized_query = normalized_search_text(query_text)
                ordered = sorted(query_terms, key=lambda t: (normalized_query.find(t), t))
                query_terms = set(ordered[:48] + ordered[-48:])
            if query_terms:
                marks = ','.join('?' for _ in query_terms)
                frequencies = {r['term']: r['n'] for r in conn.execute(
                    f'SELECT term,COUNT(*) n FROM search_postings WHERE term IN ({marks}) GROUP BY term', sorted(query_terms))}
                # Rare terms protect a specific old event from being drowned by
                # thousands of newer matches on generic words such as "计划".
                weights = {t: 1 / (1 + frequencies.get(t, 0)) for t in query_terms}
                value_params = [value for t in sorted(query_terms) for value in (t, weights[t])]
                date_clause, params = " AND (p.kind!='raw' OR (m.role IN ('user','assistant') AND c.local_day<?))", value_params + [today]
                if period:
                    date_clause = """ AND ((p.kind IN ('raw','evidence') AND c.local_day BETWEEN ? AND ?)
                        OR (p.kind='memory' AND COALESCE(a.period_start,cs.local_day)>=?
                            AND COALESCE(a.period_end,ce.local_day)<=?)) AND (p.kind!='raw' OR m.role IN ('user','assistant'))"""
                    params = value_params + [period[0], period[1], period[0], period[1]]
                if excluded:
                    excluded_marks = ','.join('?' for _ in excluded)
                    date_clause += f" AND (p.kind='memory' OR COALESCE(m.id,e.source_message_id) NOT IN ({excluded_marks}))"
                    params += sorted(excluded)
                    date_clause += f" AND (p.kind!='raw' OR COALESCE(m.reply_to_id,'') NOT IN ({excluded_marks}))"
                    params += sorted(excluded)
                values = ','.join('(?,?)' for _ in query_terms)
                rows = conn.execute(f"""WITH query_terms(term,weight) AS (VALUES {values})
                    SELECT p.kind,p.source_id,d.term_count,COUNT(*) hits FROM query_terms q
                    JOIN search_postings p ON p.term=q.term
                    JOIN search_documents d ON d.kind=p.kind AND d.source_id=p.source_id
                    LEFT JOIN messages m ON p.kind='raw' AND m.id=p.source_id
                    LEFT JOIN evidence e ON p.kind='evidence' AND e.id=p.source_id
                    LEFT JOIN message_calendar c ON c.message_id=COALESCE(m.id,e.source_message_id)
                    LEFT JOIN memories mm ON p.kind='memory' AND mm.id=p.source_id
                    LEFT JOIN archive_periods a ON a.memory_id=mm.id
                    LEFT JOIN message_calendar cs ON cs.message_id=mm.source_start_id
                    LEFT JOIN message_calendar ce ON ce.message_id=mm.source_end_id
                    WHERE 1=1{date_clause}
                    GROUP BY p.kind,p.source_id ORDER BY SUM(q.weight) DESC,hits DESC,p.source_id LIMIT 120""", params).fetchall()
                keys = [(r['kind'], r['source_id']) for r in rows]
            elif period:
                keys = [('memory', r[0]) for r in conn.execute(
                    'SELECT memory_id FROM archive_periods WHERE period_start>=? AND period_end<=? ORDER BY kind,period_start LIMIT 30',
                    (period[0], period[1])).fetchall()]
                keys += [('raw', r[0]) for r in conn.execute("""SELECT m.id FROM messages m JOIN message_calendar c ON c.message_id=m.id
                    WHERE c.local_day BETWEEN ? AND ? AND m.role='user' ORDER BY m.timestamp,m.rowid LIMIT 40""", period[:2]).fetchall()]
            else:
                return []
            # Load the bounded candidate set in batches. Ranking must not issue
            # one query per candidate/reply/archive (up to 360+ SELECTs per turn).
            raw, evidence, memories, replies, blocked_memories, daily_archives = self._load_candidates(conn, keys, excluded)
            candidates, seen = [], set()
            now = datetime.now(UTC)
            for kind, source_id in keys:
                if (kind, source_id) in seen:
                    continue
                seen.add((kind, source_id))
                if kind == 'raw':
                    if source_id in excluded:
                        continue
                    row = raw.get(source_id)
                    if not row or row['role'] == 'system' or row['reply_to_id'] in excluded or (not period and row['local_day'] >= today):
                        continue
                    original = row['content']
                    text = f"[{row['local_day']} historical quotation, not current fact] {row['role']}: {self._excerpt(original, query_terms)}"
                    reply = replies.get(source_id)
                    if reply and reply['id'] not in excluded:
                        text += '\nassistant: ' + reply['content'][:300]
                    timestamp, importance, confidence = row['timestamp'], 0.6, 1.0
                    source_message_id, day, output_kind = row['id'], row['local_day'], 'raw'
                    archive_id = None
                elif kind == 'evidence':
                    row = evidence.get(source_id)
                    if not row or row['source_message_id'] in excluded or row['importance'] < 0.6:
                        continue
                    if row['expires_at'] and datetime.fromisoformat(row['expires_at']) <= now and not period:
                        continue
                    original = row['key'] + ': ' + str(json.loads(row['value_json']))
                    text = f"[{row['local_day']} observed then, not necessarily current] {original}"
                    timestamp, importance, confidence = row['created_at'], row['importance'], row['confidence']
                    source_message_id, day, output_kind = row['source_message_id'], row['local_day'], 'evidence'
                    archive_id = None
                else:
                    row = memories.get(source_id)
                    if not row:
                        continue
                    if source_id in blocked_memories:
                        continue
                    original = memory_text(json.loads(row['content_json']))
                    label = row['period_start'] or row['period_key'] or 'past'
                    if row['period_end'] and row['period_end'] != label:
                        label += '..' + row['period_end']
                    text = f"[{label} historical {row['kind']} summary, not current fact] {self._excerpt(original, query_terms)}"
                    timestamp, importance, confidence = row['created_at'], row['importance'], row['confidence']
                    source_message_id, day, output_kind = None, row['period_start'], row['kind']
                    archive_id = source_id if row['period_start'] else None
                item_terms = terms(original)
                if query_terms:
                    matches = query_terms & item_terms
                    coverage = sum(weights[t] for t in matches) / max(1e-9, sum(weights.values()))
                    cosine = len(matches) / max(1, math.sqrt(len(query_terms) * max(1, len(item_terms))))
                    relevance = 0.7 * coverage + 0.3 * cosine
                else:
                    relevance = 1.0
                try:
                    age = max(0, (now - datetime.fromisoformat(timestamp)).total_seconds() / 86400)
                except (TypeError, ValueError):
                    age = 365
                score = 0.55 * relevance + 0.15 * math.exp(-age / 90) + 0.18 * importance + 0.12 * confidence
                if period:
                    score += 0.2
                if (query_terms and relevance == 0) or score < 0.24:
                    continue
                candidates.append(dict(kind=output_kind, id=source_id, text=text[:1800], timestamp=timestamp,
                    importance=importance, confidence=confidence, score=round(score, 5), lexical_relevance=relevance,
                    source_message_id=source_message_id, archive_id=archive_id or daily_archives.get(day),
                    local_day=day, date_filter=list(period[:2]) if period else None))
        candidates.sort(key=lambda x: x['score'], reverse=True)
        result, sources = [], set()
        for item in candidates:
            source = item['source_message_id'] or item['id']
            if source in sources:
                continue
            sources.add(source)
            result.append(item)
            if len(result) >= max(1, limit):
                break
        return result

    @staticmethod
    def _load_candidates(conn, keys, excluded):
        groups = {kind: sorted({source_id for k, source_id in keys if k == kind})
                  for kind in ('raw', 'evidence', 'memory')}
        loaded = {}
        statements = {
            'raw': '''SELECT m.*,c.local_day FROM messages m
                JOIN message_calendar c ON c.message_id=m.id WHERE m.id IN ({marks})''',
            'evidence': '''SELECT e.*,c.local_day FROM evidence e
                JOIN message_calendar c ON c.message_id=e.source_message_id WHERE e.id IN ({marks})''',
            'memory': '''SELECT m.*,a.period_start,a.period_end FROM memories m
                LEFT JOIN archive_periods a ON a.memory_id=m.id WHERE m.id IN ({marks})''',
        }
        for kind, ids in groups.items():
            marks = ','.join('?' for _ in ids)
            loaded[kind] = {r['id']: r for r in conn.execute(statements[kind].format(marks=marks), ids)} if ids else {}
        replies = {}
        if groups['raw']:
            marks = ','.join('?' for _ in groups['raw'])
            # MIN(rowid) preserves the first inserted assistant reply, even if
            # timestamps tie or a later retry exists. Non-assistant links are
            # never mislabeled as an assistant quotation.
            replies = {r['reply_to_id']: r for r in conn.execute(f'''SELECT m.id,m.reply_to_id,m.content
                FROM messages m JOIN (SELECT MIN(rowid) first_row FROM messages
                    WHERE reply_to_id IN ({marks}) AND role='assistant' GROUP BY reply_to_id) first
                ON m.rowid=first.first_row''', groups['raw'])}
        blocked = set()
        if groups['memory'] and excluded:
            marks = ','.join('?' for _ in groups['memory'])
            exclusions = sorted(excluded)
            for offset in range(0, len(exclusions), 400):
                batch = exclusions[offset:offset + 400]
                excluded_marks = ','.join('?' for _ in batch)
                blocked.update(r[0] for r in conn.execute(f'''SELECT DISTINCT memory_id FROM memory_sources
                    WHERE memory_id IN ({marks}) AND source_message_id IN ({excluded_marks})''',
                    groups['memory'] + batch))
        days = sorted({r['local_day'] for kind in ('raw', 'evidence') for r in loaded[kind].values()}
                      | {r['period_start'] for r in loaded['memory'].values() if r['period_start']})
        daily = {}
        if days:
            marks = ','.join('?' for _ in days)
            daily = {r['period_start']: r['memory_id'] for r in conn.execute(f'''SELECT period_start,memory_id
                FROM archive_periods WHERE kind='daily' AND period_start IN ({marks})''', days)}
        return loaded['raw'], loaded['evidence'], loaded['memory'], replies, blocked, daily

    @staticmethod
    def _memory_text(memory):
        return memory_text(memory['content'])

    @staticmethod
    def _excerpt(text, query_terms, width=500):
        if len(text) <= width:
            return text
        # Normalization can change offsets (half-width voiced kana is two source
        # characters). Use exact offsets first; normalized spelling is for search.
        lowered = text.casefold()
        positions = [lowered.find(t) for t in query_terms if len(t) >= 2]
        if not any(p >= 0 for p in positions):
            normalized, source_offsets = normalized_search_offsets(text)
            normalized_positions = [normalized.find(t) for t in query_terms if len(t) >= 2]
            positions = [source_offsets[p] for p in normalized_positions if p >= 0]
        position = min((p for p in positions if p >= 0), default=0)
        start = max(0, position - 60)
        return ('…' if start else '') + text[start:start + width] + ('…' if start + width < len(text) else '')
