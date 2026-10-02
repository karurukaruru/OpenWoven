"""Bounded model-written weekly summaries, with persistent retry throttling."""
from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

from .context import estimate_tokens


class WeeklySummarizer:
    def __init__(self, store, generate):
        self.store, self.generate = store, generate
        self._lock = threading.Lock()

    def ready(self, start, end):
        retry = self.store.get_metadata(f'weekly_summary_retry:{start}..{end}')
        if retry:
            try:
                return datetime.fromisoformat(retry) <= datetime.now(UTC)
            except (ValueError, TypeError):
                pass
        return True

    def summarize(self, messages, evidence, start, end):
        if not self._lock.acquire(blocking=False):
            return None
        try:
            retry_key = f'weekly_summary_retry:{start}..{end}'
            now = datetime.now(UTC)
            if not self.ready(start, end):
                return None
            # Persist before requesting: process death must not retry repeatedly.
            self.store.set_metadata(retry_key, (now + timedelta(hours=1)).isoformat())
            with self.store.connection() as conn:
                dates = dict(conn.execute('SELECT message_id,local_day FROM message_calendar WHERE local_day BETWEEN ? AND ?', (start, end)).fetchall())
            days = {}
            for message in messages:
                days.setdefault(dates.get(message.id, message.timestamp[:10]), []).append(message)
            records = []
            budget = 4500
            for day, items in sorted(days.items()):
                # Sample across each day, not just the newest part of the week.
                allowance = max(100, budget // max(1, len(days)))
                samples = []
                step = max(1, len(items) // 16)
                for item in items[::step][:16]:
                    text = item.content[:min(800, max(1, allowance - 30))]
                    cost = estimate_tokens(text) + 20
                    if cost > allowance:
                        continue
                    samples.append({'role': item.role, 'text': text})
                    allowance -= cost
                records.append({'day': day, 'excerpts': samples})
            facts = [{'type': e.type, 'key': e.key, 'value': str(e.value)[:300]}
                     for e in evidence[:30]]
            prompt = json.dumps({'period_start': start, 'period_end': end,
                'note': 'Excerpts are a bounded sample, not the entire conversation. Do not claim exhaustive coverage.',
                'records': records, 'recorded_signals': facts}, ensure_ascii=False)
            # JSON escaping and evidence must count toward the request budget too.
            while estimate_tokens(prompt) > 5000 and (facts or any(r['excerpts'] for r in records)):
                if facts:
                    facts.pop()
                else:
                    max(records, key=lambda r: len(r['excerpts']))['excerpts'].pop()
                prompt = json.dumps({'period_start': start, 'period_end': end,
                    'note': 'Bounded excerpts; do not claim exhaustive coverage.',
                    'records': records, 'recorded_signals': facts}, ensure_ascii=False)
            try:
                summary = self.generate(prompt, f'{start}..{end}')
                if not isinstance(summary, str) or not summary.strip() or len(summary) > 6000:
                    raise ValueError('invalid weekly summary')
            except Exception:
                self.store.set_metadata('memory_maintenance_error', 'WeeklySummaryFailed')
                return None
            return summary.strip()
        finally:
            self._lock.release()
