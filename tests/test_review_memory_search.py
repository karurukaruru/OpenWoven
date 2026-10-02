from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from adaptive_companion.memory import MemoryManager
from adaptive_companion.models import Evidence
from adaptive_companion.retrieval import MemoryRetriever
from adaptive_companion.search_terms import term_occurrences, terms
from adaptive_companion.storage import SQLiteStore


class MultilingualSearchReviewTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStore(':memory:', utc_offset_minutes=0)
        self.old = (datetime.now(UTC) - timedelta(days=3)).isoformat()

    def tearDown(self):
        self.store.close()

    def test_kana_mixed_scripts_and_widths_have_matching_postings(self):
        self.assertTrue(terms('コーヒー'))
        self.assertEqual(terms('コーヒー'), terms('ｺｰﾋｰ'))
        self.assertEqual(terms('ゲーム'), terms('ケ\u3099ーム'))
        self.assertTrue({'大好', '好き', 'きな', 'なコ', 'コー', 'ーヒ', 'ヒー'} <= terms('大好きなコーヒー'))
        self.assertEqual({'café'}, terms('ＣＡＦÉ'))
        self.assertEqual({'coffee'}, terms('Coffee coffee'))

    def test_japanese_raw_memory_is_retrievable_without_a_model_call(self):
        source = self.store.save_message('ja', 'user', '先週はコーヒーを飲んだ', timestamp=self.old,
                                         learning_status='disabled')
        result = MemoryRetriever(self.store).retrieve('ｺｰﾋｰ')
        self.assertTrue(any(item['source_message_id'] == source.id for item in result))
        self.assertIn('historical quotation', result[0]['text'])

    def test_normalized_match_excerpt_still_quotes_the_original_long_tail(self):
        text = ('ｶﾞ' * 1000) + '好きなのはｺｰﾋｰです' + ('余談' * 300)
        excerpt = MemoryRetriever._excerpt(text, terms('コーヒー'))
        self.assertIn('ｺｰﾋｰ', excerpt)
        self.assertLess(len(excerpt), 503)
        self.assertTrue(excerpt.startswith('…'))

    def test_occurrences_drive_stable_topic_frequency_not_set_order(self):
        self.assertEqual(['coffee', 'tea', 'coffee'], list(term_occurrences('coffee tea coffee')))
        text = ('高数考试 ' * 100) + '乌龙茶 乐理 编译器 鸡肉饭 球鞋 寿司 奶茶 爵士乐'
        self.assertEqual(['高数', '数考', '考试'], MemoryManager._top_tags(text)[:3])
        self.assertEqual(['zebra', 'apple'], MemoryManager._top_tags('zebra apple'))

    def test_repeated_filler_does_not_displace_meaningful_topics(self):
        text = ('哈哈 嗯 好的 这个 然后 就是 はい です ' * 50) + 'コーヒー 高数考试'
        tags = MemoryManager._top_tags(text)
        self.assertIn('コー', tags)
        self.assertIn('高数', tags)
        self.assertNotIn('哈哈', tags)
        self.assertNotIn('はい', tags)

    def test_index_upgrade_covers_raw_evidence_and_summary_only_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.db'
            original = SQLiteStore(path, utc_offset_minutes=0)
            source = original.save_message('ja', 'user', 'コーヒー', timestamp=self.old, learning_status='complete')
            original.save_evidence([Evidence('ev_synthetic', 'preference', 'profile.likes', 'コーヒー',
                                            source_message_id=source.id, importance=0.8)])
            memory_id = original.upsert_memory('rolling', 'synthetic', {'facts': ['コーヒー']}, source.id,
                                              source.id, [], source_message_ids=[source.id])
            with original.connection() as conn:
                conn.execute("DELETE FROM metadata WHERE key='search_tokenizer_version'")
                conn.execute('DELETE FROM search_postings')
                conn.execute('UPDATE search_documents SET term_count=0')
                conn.commit()
            original.close()
            upgraded = SQLiteStore(path, utc_offset_minutes=0)
            self.assertEqual('2', upgraded.get_metadata('search_tokenizer_version'))
            with upgraded.connection() as conn:
                indexed = {(row['kind'], row['source_id']) for row in conn.execute(
                    "SELECT kind,source_id FROM search_postings WHERE term='コー'")}
            self.assertEqual({('raw', source.id), ('evidence', 'ev_synthetic'), ('memory', memory_id)}, indexed)
            upgraded.close()
            with patch.object(SQLiteStore, '_index', side_effect=AssertionError('unnecessary lifetime reindex')):
                reopened = SQLiteStore(path, utc_offset_minutes=0)
                reopened.close()

    def test_index_upgrade_resumes_after_committed_bounded_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resume.db'
            original = SQLiteStore(path)
            with original.connection() as conn:
                for index in range(300):
                    original.save_message('ja', 'user', 'ゲーム', learning_status='disabled',
                                          message_id=f'synthetic_{index}', connection=conn)
                conn.execute("DELETE FROM metadata WHERE key='search_tokenizer_version'")
                conn.execute('DELETE FROM search_postings')
                conn.execute('UPDATE search_documents SET term_count=0')
                conn.commit()
            original.close()
            index_document = SQLiteStore._index
            calls = 0

            def interrupted(conn, kind, source_id, text):
                nonlocal calls
                calls += 1
                if calls == 257:
                    raise RuntimeError('synthetic process interruption')
                index_document(conn, kind, source_id, text)

            with patch.object(SQLiteStore, '_index', side_effect=interrupted):
                with self.assertRaisesRegex(RuntimeError, 'synthetic process interruption'):
                    SQLiteStore(path)
            with closing(sqlite3.connect(path)) as conn:
                cursor = conn.execute("SELECT value FROM metadata WHERE key='search_tokenizer_v2_cursor:raw'").fetchone()[0]
                count = conn.execute("SELECT COUNT(*) FROM search_postings WHERE term='ゲー'").fetchone()[0]
                self.assertEqual('256', cursor)
                self.assertEqual(256, count)
            with patch.object(SQLiteStore, '_index', wraps=index_document) as writes:
                resumed = SQLiteStore(path)
                self.assertEqual(44, writes.call_count)
                self.assertEqual('2', resumed.get_metadata('search_tokenizer_version'))
                self.assertIsNone(resumed.get_metadata('search_tokenizer_v2_cursor:raw'))
                resumed.close()


class RollingMemoryReviewTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStore(':memory:', utc_offset_minutes=0)
        self.manager = MemoryManager(self.store, message_threshold=1)

    def tearDown(self):
        self.store.close()

    def message(self, text, state='complete', timestamp=None):
        return self.store.save_message('review', 'user', text, learning_status=state, timestamp=timestamp)

    def test_failed_learning_is_incomplete_not_a_lifetime_summary_block(self):
        failed = self.message('今天学习如何制作咖啡', 'failed')
        complete = self.message('今年九月要准备高数考试')
        # Even residual evidence from the failed source must not become a
        # falsely successful extracted profile fact.
        self.store.save_evidence([Evidence('failed_ev', 'profile_fact', 'profile.job', 'must not be learned',
                                          source_message_id=failed.id)])
        summary = self.manager.maybe_create_rolling_summary('review')
        self.assertTrue(summary['learning_incomplete'])
        self.assertEqual([], summary['new_user_facts'])
        self.assertEqual(complete.id, self.store.get_metadata('rolling_last:review'))
        memory = self.store.list_memories('rolling')[0]
        with self.store.connection() as conn:
            sources = {row[0] for row in conn.execute('SELECT source_message_id FROM memory_sources WHERE memory_id=?',
                                                     (memory['id'],))}
        self.assertEqual({failed.id, complete.id}, sources)
        self.assertEqual('failed', self.store.get_message(failed.id).learning_status)

    def test_pending_or_processing_is_a_hard_contiguous_cursor_fence(self):
        for state in ('pending', 'processing'):
            with self.subTest(state=state):
                self.store.clear_user_data()
                first = self.message('最近在练习吉他和乐理')
                blocked = self.message('这条观察还没有完成', state)
                later = self.message('后面想要看一场爵士乐演出')
                summary = self.manager.maybe_create_rolling_summary('review')
                self.assertIsNotNone(summary)
                self.assertEqual(first.id, self.store.get_metadata('rolling_last:review'))
                self.assertIsNone(self.manager.maybe_create_rolling_summary('review'))
                self.store.update_learning_status(blocked.id, 'complete')
                self.assertIsNotNone(self.manager.maybe_create_rolling_summary('review'))
                self.assertEqual(later.id, self.store.get_metadata('rolling_last:review'))

    def test_rolling_reads_bounded_prefixes_without_gaps_or_timestamp_reordering(self):
        with self.store.connection() as conn:
            messages = [self.store.save_message('review', 'user', '最近在学习吉他乐理', learning_status='complete',
                        timestamp=f'2026-09-{30 - index % 28:02}T12:00:00+00:00', connection=conn)
                        for index in range(270)]
            conn.commit()
        self.assertIsNotNone(self.manager.maybe_create_rolling_summary('review'))
        self.assertEqual(messages[255].id, self.store.get_metadata('rolling_last:review'))
        self.assertIsNotNone(self.manager.maybe_create_rolling_summary('review'))
        self.assertEqual(messages[-1].id, self.store.get_metadata('rolling_last:review'))
        with self.store.connection() as conn:
            sources = list(conn.execute('SELECT source_message_id FROM memory_sources'))
            plan = conn.execute('EXPLAIN QUERY PLAN SELECT id FROM messages WHERE conversation_id=? AND rowid>? ORDER BY rowid LIMIT ?',
                                ('review', 0, 256)).fetchall()
        self.assertEqual(270, len(sources))
        self.assertEqual(270, len({row[0] for row in sources}))
        self.assertFalse(any('TEMP B-TREE' in str(row[3]) for row in plan))

    def test_long_low_density_prefix_closes_without_losing_later_informative_turn(self):
        with self.store.connection() as conn:
            for index in range(256):
                self.store.save_message('review', 'user', '嗯', learning_status='disabled', connection=conn)
            informative = self.store.save_message('review', 'user', '今年九月要准备高数考试',
                                                   learning_status='complete', connection=conn)
            conn.commit()
        first = self.manager.maybe_create_rolling_summary('review')
        self.assertTrue(first['low_information'])
        self.assertEqual([], first['active_topics'])
        second = self.manager.maybe_create_rolling_summary('review')
        self.assertIsNotNone(second)
        self.assertEqual(informative.id, self.store.get_metadata('rolling_last:review'))
        self.assertEqual(257, self.store.count_messages('review'))

    def test_rejected_summary_does_not_advance_the_cursor(self):
        self.message('最近在学习吉他和乐理')
        with patch.object(self.store, 'upsert_memory', return_value=None):
            self.assertIsNone(self.manager.maybe_create_rolling_summary('review'))
        self.assertIsNone(self.store.get_metadata('rolling_last:review'))


if __name__ == '__main__':
    unittest.main()
