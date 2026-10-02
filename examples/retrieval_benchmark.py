"""Synthetic SQLite recall benchmark; no credentials, model calls or user data.

Times cover warm retrieval only, not fixture setup, startup or LLM latency.
SQL counts are a deterministic regression signal; timings are machine-specific.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from adaptive_companion.retrieval import MemoryRetriever
from adaptive_companion.storage import SQLiteStore


class MeasuredStore(SQLiteStore):
    select_count = 0

    @contextmanager
    def connection(self):
        with super().connection() as conn:
            def record(statement):
                if statement.lstrip().upper().startswith(('SELECT', 'WITH')):
                    self.select_count += 1
            conn.set_trace_callback(record)
            try:
                yield conn
            finally:
                conn.set_trace_callback(None)

    def local_today(self, now=None):
        # Fixed clock: the fixture remains historical after moving machines.
        return date(2026, 4, 1).isoformat()


def populate(store, messages=1500):
    rows = []
    for i in range(messages):
        text = 'synthetic comet itinerary' if i < 180 else f'unrelated noise {i}'
        rows.append((f'user_{i:06d}', 'benchmark', 'user', text, None))
        rows.append((f'reply_{i:06d}', 'benchmark', 'assistant', f'synthetic answer {i}', f'user_{i:06d}'))
    with store.connection() as conn:
        conn.executemany('''INSERT INTO messages
            (id,conversation_id,role,content,reply_to_id,timestamp,token_count,learning_status)
            VALUES(?,?,?,?,?,'2026-01-10T12:00:00+00:00',8,'disabled')''', rows)
        conn.commit()
    store.initialize()  # Use the normal index/calendar backfill, not a private fixture index.


def run(messages=1500, repeats=9):
    if messages < 180 or repeats < 1:
        raise ValueError('messages must be >=180 and repeats >=1')
    with tempfile.TemporaryDirectory(prefix='companion-benchmark-') as directory:
        store = MeasuredStore(Path(directory) / 'synthetic.db', utc_offset_minutes=0)
        try:
            populate(store, messages)
            retriever = MemoryRetriever(store)
            retriever.retrieve('comet itinerary', limit=8)  # warm up
            samples, counts = [], []
            for _ in range(repeats):
                store.select_count = 0
                start = time.perf_counter()
                results = retriever.retrieve('comet itinerary', limit=8)
                samples.append((time.perf_counter() - start) * 1000)
                counts.append(store.select_count)
                assert len(results) == 8 and all('comet' in item['text'] for item in results)
            return {'fixture_messages': messages * 2, 'candidate_cap': 120, 'repeats': repeats,
                    'median_ms': round(statistics.median(samples), 3),
                    'min_ms': round(min(samples), 3), 'max_ms': round(max(samples), 3),
                    'select_statements': counts, 'result_ids': [item['id'] for item in results]}
        finally:
            store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--messages', type=int, default=1500, help='synthetic user turns (each has one reply)')
    parser.add_argument('--repeats', type=int, default=9)
    args = parser.parse_args()
    print(json.dumps(run(args.messages, args.repeats), indent=2))
