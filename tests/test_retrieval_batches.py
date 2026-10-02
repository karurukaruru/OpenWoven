from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.core import CompanionCore
from adaptive_companion.models import Evidence
from adaptive_companion.retrieval import MemoryRetriever
from adaptive_companion.storage import SQLiteStore
from examples.retrieval_benchmark import MeasuredStore, populate


class RetrievalBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MeasuredStore(Path(self.tmp.name) / 'synthetic.db', utc_offset_minutes=0)
        self.retriever = MemoryRetriever(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def message(self, content='comet itinerary', role='user', **kwargs):
        return self.store.save_message('default', role, content, learning_status='disabled',
                                       timestamp='2026-01-10T12:00:00+00:00', **kwargs)

    def test_120_candidates_use_five_selects_and_preserve_tie_order(self):
        populate(self.store, messages=180)
        self.store.select_count = 0
        results = self.retriever.retrieve('comet itinerary', limit=8)
        self.assertEqual(5, self.store.select_count)
        self.assertEqual([f'user_{i:06d}' for i in range(8)], [r['id'] for r in results])
        self.assertIn('assistant: synthetic answer 0', results[0]['text'])

    def test_reply_batch_keeps_first_assistant_not_last_retry_or_linked_user(self):
        user = self.message()
        self.message('not an assistant', reply_to_id=user.id)
        self.message('first reply', role='assistant', reply_to_id=user.id)
        self.message('later retry', role='assistant', reply_to_id=user.id)
        found = self.retriever.retrieve('comet')[0]
        self.assertIn('assistant: first reply', found['text'])
        self.assertNotIn('not an assistant', found['text'])
        self.assertNotIn('later retry', found['text'])

    def test_excluded_reply_is_not_reintroduced_as_a_raw_quote(self):
        user = self.message()
        reply = self.message('excluded private reply', role='assistant', reply_to_id=user.id)
        found = self.retriever.retrieve('comet', exclude_message_ids={reply.id})
        self.assertTrue(found)
        self.assertNotIn('private reply', str(found))

    def test_mixed_batches_keep_sources_dates_expiration_and_archive_links(self):
        user = self.message()
        self.store.save_evidence([Evidence(id='event_evidence', type='event', key='current.recent_events',
            value='comet itinerary confirmed', source_message_id=user.id, importance=0.9,
            created_at='2026-01-10T12:00:00+00:00', expires_at='2026-01-11T00:00:00+00:00')])
        memory = self.store.upsert_memory('daily', '2026-01-10', {'summary': 'comet itinerary archive'},
            user.id, user.id, ['comet'], source_message_ids=[user.id])
        with self.store.connection() as conn:
            conn.execute('INSERT INTO archive_periods VALUES(?,?,?,?,?,?)',
                         (memory, 'daily', '2026-01-10', '2026-01-10', '2026-01-11T00:00:00+00:00', 1))
            conn.commit()
        undated = self.retriever.retrieve('comet', limit=20)
        self.assertNotIn('event_evidence', [r['id'] for r in undated])
        dated = self.retriever.retrieve('2026-01-10 comet', limit=20)
        self.assertIn(memory, [r['id'] for r in dated])
        # Raw and evidence sharing a source are intentionally deduplicated.
        historical_evidence = self.retriever.retrieve('2026-01-10 confirmed', limit=20)
        self.assertIn('event_evidence', [r['id'] for r in historical_evidence])
        self.assertTrue(all(r['archive_id'] == memory for r in dated + historical_evidence))
        self.assertEqual([], self.retriever.retrieve('comet', exclude_message_ids={user.id}))
        self.assertEqual([], self.retriever.retrieve('2026-01-10 那天聊了什么', exclude_message_ids={user.id}))

    def test_day_only_and_deleted_sources_do_not_leave_cached_candidates(self):
        user = self.message()
        found = self.retriever.retrieve('2026-01-10 那天聊了什么')
        self.assertEqual([user.id], [r['id'] for r in found])
        with self.store.connection() as conn:
            conn.execute('DELETE FROM messages WHERE id=?', (user.id,))
            conn.commit()
        self.assertEqual([], self.retriever.retrieve('2026-01-10 comet'))

    def test_reply_index_is_added_idempotently_to_existing_v8(self):
        with self.store.connection() as conn:
            conn.execute('DROP INDEX idx_messages_reply_to')
            conn.commit()
        self.store.initialize()
        self.store.initialize()
        with self.store.connection() as conn:
            self.assertEqual(11, conn.execute('PRAGMA user_version').fetchone()[0])
            indexes = {r['name'] for r in conn.execute('PRAGMA index_list(messages)')}
            self.assertIn('idx_messages_reply_to', indexes)

    def test_android_reads_one_old_message_without_loading_the_history_window(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            core.wait_for_learning()
            oldest = core.store.save_message('default', 'user', 'old pending source',
                timestamp='2026-01-01T12:00:00+00:00')
            with core.store.connection() as conn:
                conn.executemany('''INSERT INTO messages
                    (id,conversation_id,role,content,timestamp,token_count)
                    VALUES(?,'default','user','synthetic later message','2026-02-01T12:00:00+00:00',6)''',
                    [(f'later_{i}',) for i in range(310)])
                conn.commit()
            self.assertNotIn(oldest.id, [m.id for m in core.store.list_messages('default', 300)])
            with patch.object(android_bridge, '_core', core), patch.object(core.store, 'list_messages', side_effect=AssertionError('history scan')):
                self.assertEqual(oldest.id, json.loads(android_bridge.get_message(oldest.id))['id'])
                self.assertIsNone(json.loads(android_bridge.get_message('missing')))
                core.delete_message(oldest.id)
                self.assertIsNone(json.loads(android_bridge.get_message(oldest.id)))


if __name__ == '__main__':
    unittest.main()
