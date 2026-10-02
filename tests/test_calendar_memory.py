from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from adaptive_companion.calendar_time import resolve_period
from adaptive_companion.core import CompanionCore
from adaptive_companion.delivery import DeliveryPlanner, DeliverySettings
from adaptive_companion.llm import LLMProvider
from adaptive_companion.models import Evidence, ScheduledMessage, utc_now
from adaptive_companion.observer import RuleBasedObserver
from adaptive_companion.storage import (SQLiteStore, SCHEMA, MIGRATION_1_TO_2, MIGRATION_2_TO_3,
    MIGRATION_3_TO_4, MIGRATION_4_TO_5, MIGRATION_5_TO_6, MIGRATION_6_TO_7)


class CalendarMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'memory.db'
        self.core = CompanionCore(self.path, learning_enabled=False, memory_utc_offset_minutes=480, memory_zone_name='Asia/Shanghai')
        self.core.wait_for_learning()

    def tearDown(self):
        self.core.close()
        self.tmp.cleanup()

    def message(self, day='2026-01-10', text='今天讨论了樱花计划，决定周末去苏州旅行。', status='disabled', role='user', reply_to_id=None):
        return self.core.store.save_message('archive', role, text, learning_status=status,
            timestamp=day + 'T12:00:00+08:00', reply_to_id=reply_to_id)

    def maintain(self, day):
        return self.core.memory.maintain(datetime.fromisoformat(day + 'T12:00:00+08:00'))

    def test_closed_day_is_sealed_once_without_destroying_raw(self):
        message = self.message()
        self.assertEqual([], self.core.memory.archives.list())
        self.assertEqual(0, self.maintain('2026-01-10')['daily'])
        self.assertEqual(1, self.maintain('2026-01-11')['daily'])
        archive = self.core.memory.archives.list()[0]
        self.assertIn('樱花计划', str(archive['content']))
        self.assertEqual(message.id, self.core.memory.archives.detail(archive['memory_id'])['messages'][0]['id'])
        self.assertEqual(0, self.maintain('2026-01-11')['daily'])
        self.assertIsNotNone(self.core.store.get_message(message.id))

    def test_week_and_month_have_children_and_raw_provenance(self):
        for day in ('2026-01-05', '2026-01-10', '2026-01-20', '2026-01-31'):
            self.message(day)
        result = self.maintain('2026-02-02')
        self.assertEqual(4, result['daily'])
        self.assertEqual(1, result['monthly'])
        month = self.core.memory.archives.list('monthly')[0]
        detail = self.core.memory.archives.detail(month['memory_id'])
        self.assertEqual(4, len(detail['messages']))
        self.assertTrue(any(c['kind'] == 'weekly' for c in detail['children']))
        self.assertTrue(any(c['kind'] == 'daily' and c['period_start'] == '2026-01-31' for c in detail['children']))
        self.assertEqual(4, self.core.store.count_messages())

    def test_restart_catches_up_without_midnight_or_model_call(self):
        self.message()
        self.core.close()
        self.core = CompanionCore(self.path, learning_enabled=False, memory_utc_offset_minutes=480)
        self.core.wait_for_learning()
        self.assertEqual(1, len(self.core.memory.archives.list('monthly')))
        self.assertEqual([], self.core.store.list_generation_metrics())

    def test_pending_learning_prevents_a_premature_seal(self):
        message = self.message(status='pending')
        self.assertEqual(0, self.maintain('2026-02-02')['daily'])
        self.assertEqual([], self.core.memory.archives.list('monthly'))
        self.core.store.update_learning_status(message.id, 'complete')
        self.assertEqual(1, self.maintain('2026-02-02')['monthly'])

    def test_failed_learning_does_not_lose_the_original(self):
        message = self.message(status='failed')
        self.maintain('2026-02-02')
        archive = self.core.memory.archives.list()[0]
        self.assertTrue(archive['content']['learning_incomplete'])
        self.assertEqual(message.content, self.core.memory.archives.detail(archive['memory_id'])['messages'][0]['content'])

    def test_late_evidence_marks_sealed_day_week_and_month_dirty(self):
        message = self.message()
        self.maintain('2026-02-02')
        self.core.store.save_evidence([Evidence(id='late', type='event', key='current.recent_events',
            value='樱花计划最终取消', source_message_id=message.id)])
        result = self.maintain('2026-02-02')
        self.assertEqual((1, 1, 1), (result['daily'], result['weekly'], result['monthly']))
        self.assertIn('最终取消', str(self.core.memory.archives.list('monthly')[0]['content']))

    def test_timezone_boundary_and_existing_day_survives_zone_change(self):
        message = self.core.store.save_message('tz', 'user', '凌晨聊天', learning_status='disabled', timestamp='2026-01-10T17:01:00+00:00')
        self.maintain('2026-01-12')
        self.assertEqual('2026-01-11', self.core.memory.archives.list()[0]['period_start'])
        reopened = SQLiteStore(self.path, utc_offset_minutes=0)
        with reopened.connection() as conn:
            self.assertEqual('2026-01-11', conn.execute('SELECT local_day FROM message_calendar WHERE message_id=?', (message.id,)).fetchone()[0])

    def test_date_and_keyword_retrieval_reaches_three_month_old_original(self):
        old = self.message('2026-01-10', '那天我们给猫取名叫龙眼，后来去了南门咖啡店。')
        self.message('2026-01-20', '南门咖啡店已经关闭，今天是另一天。')
        self.maintain('2026-04-01')
        found = self.core.retriever.retrieve('第一个月的第二周的第三天 龙眼')
        self.assertTrue(found)
        self.assertTrue(any(item['source_message_id'] == old.id for item in found))
        self.assertTrue(all(item['date_filter'] == ['2026-01-10', '2026-01-10'] for item in found))
        self.assertNotIn('已经关闭', str(found))
        detail = self.core.memory.archives.detail(found[0]['archive_id'])
        self.assertTrue(any(m['content'] == old.content for m in detail['messages']))

    def test_date_only_search_returns_that_days_records_not_other_month_days(self):
        self.message()
        self.message('2026-01-20', '错误日期的内容')
        self.maintain('2026-02-02')
        found = self.core.retriever.retrieve('2026-01-10 那天聊了什么')
        self.assertTrue(found)
        self.assertNotIn('错误日期', str(found))

    def test_indexed_search_is_not_limited_to_newest_five_hundred_records(self):
        old = self.message('2026-01-10', '古早唯一线索：天文望远镜的暗号是蓝鲸。')
        # Simulate a long history cheaply in one transaction, then backfill using
        # the same startup path used by a schema migration.
        with self.core.store.connection() as conn:
            conn.executemany('INSERT INTO messages(id,conversation_id,role,content,timestamp,token_count,learning_status) VALUES(?,?,?,?,?,?,?)',
                [(f'later_{i}', 'noise', 'user', f'无关聊天 第{i}条', '2026-02-20T12:00:00+08:00', 6, 'disabled') for i in range(600)])
            conn.commit()
        self.core.store.initialize()
        found = self.core.retriever.retrieve('天文望远镜 蓝鲸')
        self.assertTrue(any(item['source_message_id'] == old.id for item in found))

    def test_raw_keyword_match_far_beyond_the_prefix_keeps_the_matching_quote(self):
        self.message(text='旧内容。' * 500 + '最后确定的暗号叫雪豹。')
        found = self.core.retriever.retrieve('雪豹')
        self.assertIn('雪豹', found[0]['text'])
        self.assertLess(len(found[0]['text']), 650)

    def test_a_specific_old_event_is_not_drowned_by_a_common_word(self):
        old = self.message(text='计划的暗号是海狸，我们安排了下个月的远行。')
        with self.core.store.connection() as conn:
            conn.executemany('INSERT INTO messages(id,conversation_id,role,content,timestamp,token_count,learning_status) VALUES(?,?,?,?,?,?,?)',
                [(f'common_{i}', 'noise', 'user', '计划', '2026-02-20T12:00:00+08:00', 2, 'disabled') for i in range(150)])
            conn.commit()
        self.core.store.initialize()
        self.assertTrue(any(item['source_message_id'] == old.id for item in self.core.retriever.retrieve('计划 海狸')))

    def test_very_long_search_avoids_sqlite_parameter_limits(self):
        self.message(text='末尾线索 银河系漫游指南')
        query = ' '.join(f'unique{i}' for i in range(1500)) + ' 银河系漫游指南'
        self.assertTrue(self.core.retriever.retrieve(query))

    def test_old_assistant_suggestions_are_searchable_but_an_old_retry_answer_is_excluded(self):
        user = self.message(text='上次你推荐给我的书是什么？')
        reply = self.message(role='assistant', text='我推荐你读《银河系漫游指南》。', reply_to_id=user.id)
        found = self.core.retriever.retrieve('银河系漫游指南')
        self.assertTrue(any(item['source_message_id'] == reply.id for item in found))
        self.assertEqual([], self.core.retriever.retrieve('银河系漫游指南', exclude_message_ids={user.id}))

    def test_monthly_summary_is_loaded_as_history_with_a_bounded_prompt(self):
        self.message()
        self.maintain('2026-02-02')
        memories = [item for item in self.core.retriever.retrieve('2026-01 樱花计划') if item['kind'] == 'monthly']
        self.assertTrue(memories)
        context = self.core.context_builder.build(self.core.aul(), self.core.current_policy('樱花计划'),
            '樱花计划', [], memories, budget=1800)
        self.assertTrue(context['historical_summaries'])
        self.assertLessEqual(context['estimated_tokens'], 1800)

    def test_archive_detail_is_paginated(self):
        for i in range(55):
            self.message(text=f'今天记录了第 {i} 件事情。')
        self.maintain('2026-01-11')
        archive_id = self.core.memory.archives.list()[0]['memory_id']
        self.assertEqual(50, len(self.core.memory.archives.detail(archive_id)['messages']))
        self.assertEqual(5, len(self.core.memory.archives.detail(archive_id, 50)['messages']))

    def test_deletion_clears_every_derived_copy_and_allows_safe_rebuild(self):
        private = self.message(text='私密暗号是孔雀石。')
        kept = self.message(text='今天去了公园晒太阳。')
        self.maintain('2026-02-02')
        self.core.delete_message(private.id)
        self.assertEqual([], self.core.retriever.retrieve('孔雀石'))
        self.assertEqual([], self.core.memory.archives.list('monthly'))
        self.maintain('2026-02-02')
        self.assertNotIn('孔雀石', str(self.core.store.list_memories()))
        self.assertIsNotNone(self.core.store.get_message(kept.id))
        with self.core.store.connection() as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM search_postings WHERE term='孔雀'").fetchone()[0])

    def test_clear_data_clears_the_new_indexes_and_calendar_tables(self):
        self.message()
        self.maintain('2026-02-02')
        self.core.store.clear_user_data()
        with self.core.store.connection() as conn:
            for table in ('message_calendar', 'archive_periods', 'archive_dirty', 'memory_links', 'search_documents', 'search_postings'):
                self.assertEqual(0, conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], table)

    def test_duplicate_evidence_does_not_index_a_value_that_was_never_stored(self):
        message = self.message()
        self.core.store.save_evidence([Evidence(id='duplicate', type='profile_fact', key='profile.likes', value='爵士乐', source_message_id=message.id)])
        self.core.store.save_evidence([Evidence(id='duplicate', type='profile_fact', key='profile.likes', value='电子乐', source_message_id=message.id)])
        with self.core.store.connection() as conn:
            self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM search_postings WHERE kind='evidence' AND term='电子'").fetchone()[0])

    def test_v7_migration_preserves_memory_source_foreign_keys(self):
        legacy = Path(self.tmp.name) / 'v7.db'
        with closing(sqlite3.connect(legacy)) as conn:
            conn.executescript(SCHEMA + MIGRATION_1_TO_2 + MIGRATION_2_TO_3 + MIGRATION_3_TO_4 + MIGRATION_4_TO_5 + MIGRATION_5_TO_6 + MIGRATION_6_TO_7)
            conn.execute("INSERT INTO messages(id,conversation_id,role,content,timestamp,token_count) VALUES('old','default','user','古老记忆','2026-01-10T12:00:00+08:00',4)")
            conn.execute("INSERT INTO memories VALUES('summary','daily','2026-01-10',?,'old','old','[]',.8,.9,?,?)", (json.dumps({'facts': ['古老记忆']}), utc_now(), utc_now()))
            conn.execute("INSERT INTO memory_sources VALUES('summary','old')")
            conn.commit()
        migrated = SQLiteStore(legacy, utc_offset_minutes=480)
        with migrated.connection() as conn:
            self.assertEqual(11, conn.execute('PRAGMA user_version').fetchone()[0])
            self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())
            self.assertEqual(('summary', 'old'), tuple(conn.execute('SELECT * FROM memory_sources').fetchone()))
            conn.execute("DELETE FROM memories WHERE id='summary'")
            conn.commit()
            self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM memory_sources').fetchone()[0])

    def test_supported_dates_and_invalid_dates(self):
        self.assertEqual(('2026-01-10', '2026-01-10'), resolve_period('2026年1月10日 龙眼', date(2026, 4, 1))[:2])
        self.assertEqual(('2026-01-01', '2026-01-31'), resolve_period('2026-01 的旅行', date(2026, 4, 1))[:2])
        self.assertIsNone(resolve_period('2026-02-30', date(2026, 4, 1)))
        self.assertIsNone(resolve_period('以前某一天', date(2026, 4, 1)))


class TimingAndSchedulingTests(unittest.TestCase):
    def test_only_fast_casual_responses_get_a_small_extra_wait(self):
        planner = DeliveryPlanner(DeliverySettings(split_probability=0))
        fast = planner.plan('今天的天气真的不错。', 'fixed', {'context': 'casual_chat'}, 0)
        slow = planner.plan('今天的天气真的不错。', 'fixed', {'context': 'casual_chat'}, 2500)
        emotional = planner.plan('听起来你现在真的很难受。', 'fixed', {'context': 'emotional'}, 0)
        self.assertTrue(0 < fast.parts[0].delay_ms <= 900)
        self.assertEqual(0, slow.parts[0].delay_ms)
        self.assertEqual(0, emotional.parts[0].delay_ms)
        self.assertEqual(fast.parts[0].delay_ms, planner.validate(fast).parts[0].delay_ms)

    def test_code_and_technical_responses_are_not_split(self):
        planner = DeliveryPlanner(DeliverySettings(split_probability=1))
        for text, policy in [('第一步是先检查依赖。第二步是启动程序。', {'context': 'technical'}),
                             ('```python\nprint("hello")\nprint("world")\n```', {'context': 'casual_chat'})]:
            plan = planner.plan(text, 'fixed', policy)
            self.assertEqual(1, len(plan.parts))
            self.assertEqual(0, plan.parts[0].delay_ms)

    def test_explicit_reminder_uses_no_model_and_can_be_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            with CompanionCore(Path(tmp) / 'reminder.db', learning_enabled=False) as core:
                core.proactive.settings.quiet_start_hour = core.proactive.settings.quiet_end_hour = 0
                result = core.chat_result('明天20:30提醒我拿快递')
                item = core.store.get_scheduled_message(result['scheduled_message'])
                self.assertTrue(item.topic.startswith('reminder:'))
                self.assertIn('20:30', result['response'])
                count = len(core.store.list_generation_metrics())
                delivered = core.execute_scheduled(item.id, force=True)
                self.assertTrue(delivered['sent'])
                self.assertIn('拿快递', delivered['text'])
                self.assertEqual(count, len(core.store.list_generation_metrics()))
                second = core.chat_result('明天21:30提醒我取消订阅')
                self.assertIsNotNone(second['scheduled_message'])
                core.chat_result('取消提醒')
                self.assertFalse(core.execute_scheduled(second['scheduled_message'], force=True)['sent'])

    def test_invalid_or_negated_schedule_is_not_silently_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            with CompanionCore(Path(tmp) / 'invalid.db', learning_enabled=False) as core:
                for text in ('明天25:30提醒我看书', '明天20:75提醒我看书', '不要明天提醒我考试'):
                    self.assertIsNone(core.chat_result(text)['scheduled_message'])

    def test_completion_in_another_conversation_does_not_cancel_this_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            with CompanionCore(Path(tmp) / 'scope.db', learning_enabled=False) as core:
                result = core.chat_result('明天我要考试，15点结束。', 'a')
                core.chat_result('我考试考完了。', 'b')
                self.assertEqual('pending', core.store.get_scheduled_message(result['scheduled_message']).status)

    def test_cancellation_during_generation_is_rechecked_before_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            with CompanionCore(Path(tmp) / 'cancel.db', learning_enabled=False) as core:
                core.proactive.settings.quiet_start_hour = core.proactive.settings.quiet_end_hour = 0
                item_id = core.chat_result('明天我要考试，15点结束。')['scheduled_message']
                class CancellingProvider(LLMProvider):
                    def generate(self, context):
                        core.store.update_scheduled_status(item_id, 'cancelled')
                        return '不应发送的内容'
                core.provider = CancellingProvider()
                before = core.store.count_messages()
                self.assertFalse(core.execute_scheduled(item_id, force=True)['sent'])
                self.assertEqual(before, core.store.count_messages())

    def test_explicit_reminder_does_not_consume_the_automatic_care_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            with CompanionCore(Path(tmp) / 'quota.db', learning_enabled=False) as core:
                core.proactive.settings.quiet_start_hour = core.proactive.settings.quiet_end_hour = 0
                automatic = core.chat_result('明天我要考试，15点结束。')['scheduled_message']
                explicit = core.chat_result('明天9:30提醒我拿快递')['scheduled_message']
                self.assertTrue(core.execute_scheduled(explicit, force=True)['sent'])
                self.assertTrue(core.execute_scheduled(automatic, force=True)['sent'])


class AssertionLearningTests(unittest.TestCase):
    def test_negated_detail_is_not_learned_as_a_request_for_more_detail(self):
        with CompanionCore(':memory:') as core:
            before = core.aul()['interaction']['reply_length']['value']
            after = core.learn_now('我不喜欢详细解释。')['interaction']['reply_length']['value']
            self.assertLess(after, before)

    def test_negated_short_answer_does_not_make_replies_shorter(self):
        with CompanionCore(':memory:') as core:
            before = core.aul()['interaction']['reply_length']['value']
            after = core.learn_now('不要太短。')['interaction']['reply_length']['value']
            self.assertGreater(after, before)

    def test_quotes_reported_speech_and_hypotheticals_do_not_become_user_identity(self):
        with CompanionCore(':memory:') as core:
            for text in ('朋友说：“我叫张三。”', '我朋友说我叫张三。', '如果我叫张三，你怎么称呼我？',
                         '解释一下“详细解释”和“简短”的区别。', '例如，我喜欢爵士乐。',
                         "解释一下'我叫张三'这句话。", '这句话是‘我叫张三’。'):
                with self.subTest(text=text):
                    state = core.learn_now(text)
                    self.assertIsNone(state['profile']['name'])
                    self.assertEqual([], state['profile']['likes'])
                    self.assertEqual(0.5, state['interaction']['reply_length']['value'])

    def test_assertions_outside_a_quote_are_still_learned(self):
        with CompanionCore(':memory:') as core:
            state = core.learn_now('朋友说：“我叫张三。”我叫小王。')
            self.assertEqual('小王', state['profile']['name']['value'])

    def test_negated_or_other_persons_mood_is_not_learned_as_current_user_state(self):
        with CompanionCore(':memory:') as core:
            for text in ('我不焦虑。', '我的朋友很焦虑。', '他很难过。'):
                self.assertIsNone(core.learn_now(text)['current']['mood'])

    def test_learning_an_old_message_does_not_make_its_expired_mood_current_again(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            message = core.store.save_message('old', 'user', '我很焦虑。', learning_status='pending',
                timestamp=(datetime.now(UTC) - timedelta(days=30)).isoformat())
            state = core.learning.process(message.id)
            self.assertIsNone(state['current']['mood'])
            evidence = core.store.evidence_for_sources([message.id])[0]
            self.assertLess(datetime.fromisoformat(evidence.expires_at), datetime.now(UTC))


if __name__ == '__main__':
    unittest.main()
