from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.character_interview import character_generation_prompt, validated_character_draft
from adaptive_companion.context import ContextBuilder, estimate_tokens
from adaptive_companion.core import CompanionCore
from adaptive_companion.delivery import DeliveryPlanner, DeliverySettings, DeliveryPart, DeliveryPlan
from adaptive_companion.llm import compile_dialogue_prompt
from adaptive_companion.models import Evidence
from adaptive_companion.proactive import ProactiveSettings
from adaptive_companion.storage import SQLiteStore
from tests.test_natural_character_and_topics import answers, blueprint, SyntheticCharacterProvider


def quiet_off():
    return ProactiveSettings(enabled=False, quiet_start_hour=0, quiet_end_hour=0)


class ScheduledMessagesTests(unittest.TestCase):
    def setUp(self):
        self.core = CompanionCore(':memory:', provider=SyntheticCharacterProvider(), learning_enabled=False,
            proactive_settings=quiet_off(), memory_utc_offset_minutes=0)
        self.when = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()

    def tearDown(self):
        self.core.close()

    def test_exact_content_is_durable_due_only_and_does_not_call_a_model(self):
        text = '你今天中午想吃什么？我买了寿司，还有奶茶。'
        with patch.object(self.core.provider, 'generate', side_effect=AssertionError('no API')):
            job = self.core.schedule_custom(text, self.when)
            self.assertFalse(self.core.execute_scheduled(job['id'])['sent'])
            result = self.core.execute_scheduled(job['id'], force=True)
        self.assertTrue(result['sent'])
        self.assertEqual(text, result['text'])
        self.assertEqual(text, result['delivery_plan']['parts'][0]['text'])
        self.assertEqual([], self.core.store.list_generation_metrics())
        self.assertFalse(self.core.execute_scheduled(job['id'], force=True)['sent'])

    def test_topic_is_generated_only_when_due_and_user_schedules_ignore_automatic_optout(self):
        with patch.object(self.core.provider, 'generate', return_value='今天想聊什么？\n最近看书了吗') as generate:
            job = self.core.schedule_custom('聊聊之前看过的书', self.when, True)
            self.assertEqual(0, generate.call_count)
            self.assertTrue(self.core.execute_scheduled(job['id'], force=True)['sent'])
            self.assertEqual(1, generate.call_count)
        self.assertEqual('proactive', self.core.store.list_generation_metrics()[0]['kind'])

    def test_cancel_does_not_relabel_an_already_sent_message(self):
        with patch.object(android_bridge, '_core', self.core):
            job = json.loads(android_bridge.schedule_custom('later', self.when))
            self.assertEqual('cancelled', json.loads(android_bridge.cancel_scheduled(job['id']))['status'])
            self.assertFalse(self.core.execute_scheduled(job['id'], force=True)['sent'])
            sent_job = self.core.schedule_custom('later', self.when)
            self.core.execute_scheduled(sent_job['id'], force=True)
            self.assertEqual('sent', json.loads(android_bridge.cancel_scheduled(sent_job['id']))['status'])

    def test_invalid_time_content_or_parameters_never_create_a_job(self):
        invalid = ['', 'not-a-date', datetime.now().isoformat(), (datetime.now(UTC)-timedelta(minutes=1)).isoformat(),
                   (datetime.now(UTC)+timedelta(days=367)).isoformat()]
        for when in invalid:
            with self.assertRaises(ValueError):
                self.core.schedule_custom('content', when)
        for content in ['', ' ', 'x'*1001, 1]:
            with self.assertRaises(ValueError):
                self.core.schedule_custom(content, self.when)
        with self.assertRaises(ValueError):
            self.core.schedule_custom('content', self.when, generate=1)
        self.assertEqual([], self.core.store.list_scheduled_messages())

    def test_quiet_hours_shift_and_expiry_still_apply_to_explicit_schedules(self):
        self.core.proactive.settings.quiet_start_hour, self.core.proactive.settings.quiet_end_hour = 22, 8
        target = (datetime.now(UTC)+timedelta(days=1)).replace(hour=23, minute=0)
        job = self.core.schedule_custom('later', target.isoformat())
        self.assertTrue(job['quiet_adjusted'])
        shifted = datetime.fromisoformat(job['scheduled_at'])
        self.assertEqual(8, shifted.hour)
        self.assertEqual(target.date()+timedelta(days=1), shifted.date())
        self.assertFalse(self.core.proactive.revalidate(job['id'], shifted+timedelta(hours=25))[0])

    def test_offline_exact_content_works_but_model_topic_requires_configuration(self):
        with CompanionCore(':memory:', learning_enabled=False, proactive_settings=quiet_off()) as core, \
             patch('urllib.request.urlopen', side_effect=AssertionError('no network')):
            job = core.schedule_custom('offline content', self.when)
            self.assertTrue(core.execute_scheduled(job['id'], force=True)['sent'])
            with self.assertRaises(ValueError):
                core.schedule_custom('topic', self.when, True)

    def test_background_topic_without_notifications_does_not_spend_tokens(self):
        job = self.core.schedule_custom('topic', self.when, True)
        with patch.object(self.core.provider, 'generate', side_effect=AssertionError('no request')):
            self.assertEqual('notifications unavailable', self.core.execute_scheduled(job['id'], force=True, allow_casual=False)['reason'])

    def test_visible_queue_keeps_pending_messages_and_recent_closed_jobs(self):
        for i in range(60):
            job = self.core.schedule_custom('old '+str(i), self.when)
            self.core.store.update_scheduled_status(job['id'], 'cancelled')
        pending = self.core.schedule_custom('new pending', self.when)
        with patch.object(android_bridge, '_core', self.core):
            rows = json.loads(android_bridge.scheduled_queue(10))
        self.assertEqual(10, len(rows))
        self.assertEqual(pending['id'], rows[0]['id'])
        self.assertEqual('old 59', rows[1]['draft_intent'])


class ChatBubblesTests(unittest.TestCase):
    def setUp(self):
        self.planner = DeliveryPlanner(DeliverySettings(split_probability=0))
        self.casual = {'context': 'casual_chat', 'reply_length': .5}

    def test_chinese_example_is_three_natural_messages_even_with_zero_probability(self):
        text = '你今天中午想吃什么？我买了寿司，还有奶茶，然后我还会在家里做一杯咖啡。'
        parts = self.planner.plan(text, policy=self.casual).parts
        self.assertEqual(['你今天中午想吃什么？', '我买了寿司，还有奶茶', '然后我还会在家里做一杯咖啡'], [p.text for p in parts])
        self.assertTrue(all(p.delay_ms <= 2500 for p in parts))
        self.assertTrue(all(p.delay_ms >= 800 for p in parts[1:]))

    def test_very_short_chinese_reply_also_splits_and_does_not_manufacture_periods(self):
        self.assertEqual(['好呀', '明天见'], [p.text for p in self.planner.plan('好呀。明天见。', policy=self.casual).parts])
        self.assertEqual(['嗯'], [p.text for p in self.planner.plan('嗯。', policy=self.casual).parts])

    def test_quotes_code_urls_and_noncasual_prose_are_not_chopped(self):
        for text in ['他说“你好。明天见。”', '```python\nx=1\n```', '看 https://example.invalid/a.b', '1. 数字\n2. 保留']:
            self.assertEqual([text], [p.text for p in self.planner.plan(text, policy=self.casual).parts])
        text = '技术说明。保持段落。'
        self.assertEqual([text], [p.text for p in self.planner.plan(text, policy={'context': 'technical'}).parts])

    def test_bubble_limit_preserves_tail_and_disabled_timing_keeps_bubbles(self):
        text = '。'.join('片段'+str(i) for i in range(12))+'。'
        plan = self.planner.plan(text, policy=self.casual)
        self.assertLessEqual(len(plan.parts), 6)
        self.assertIn('片段11', plan.parts[-1].text)
        validated = self.planner.validate(DeliveryPlan('split', [DeliveryPart(str(i), 1) for i in range(12)]))
        self.assertIn('11', validated.parts[-1].text)
        disabled = DeliveryPlanner(DeliverySettings(enabled=False))
        parts = disabled.plan(text, policy=self.casual).parts
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(part.delay_ms == 0 for part in parts))
        self.assertIn('片段11', parts[-1].text)

    def test_requested_documents_keep_format_but_declining_an_essay_keeps_chat_style(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            policy = core.current_policy('帮我写一个通知')
            self.assertEqual('document', policy['message_format'])
            text = '这是通知的第一句。请明天准时到场。'
            self.assertEqual(text, self.planner.plan(text, policy=policy).parts[0].text)
            self.assertNotIn('message_format', core.current_policy('不要写小作文，就平常聊天'))
            self.assertEqual('document', core.current_policy('Please draft an email')['message_format'])

    def test_saved_foreground_and_scheduled_plans_survive_restart_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'synthetic.db'
            provider = SyntheticCharacterProvider()
            with CompanionCore(path, provider=provider, learning_enabled=False, proactive_settings=quiet_off()) as core:
                with patch.object(provider, 'generate', return_value='好呀。明天见。'):
                    chat = core.chat_result('聊聊今天')
                    job = core.schedule_custom('casual topic', (datetime.now(UTC)+timedelta(minutes=1)).isoformat(), True)
                    scheduled = core.execute_scheduled(job['id'], force=True)
            with CompanionCore(path, provider=provider, learning_enabled=False, proactive_settings=quiet_off()) as core, patch.object(android_bridge, '_core', core):
                rows = json.loads(android_bridge.list_messages())
                for result in [chat, scheduled]:
                    message_id = result.get('assistant_message_id', result.get('message_id'))
                    saved = next(row for row in rows if row['id'] == message_id)
                    self.assertEqual(result['delivery_plan'], saved['delivery_plan'])
                    self.assertEqual(saved, json.loads(android_bridge.get_message(message_id)))
                    core.delete_message(message_id)
                    self.assertEqual({}, core.store.delivery_plans_for([message_id]))

    def test_v8_database_upgrades_without_rewriting_legacy_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'v8.db'
            store = SQLiteStore(path)
            old = store.save_message('legacy', 'assistant', 'An existing whole reply.')
            with store.connection() as conn:
                conn.execute('DROP TABLE message_delivery_plans')
                conn.execute('DROP TABLE notification_outbox')
                conn.execute('PRAGMA user_version=8')
                conn.commit()
            store.close()
            upgraded = SQLiteStore(path)
            try:
                self.assertEqual(old, upgraded.get_message(old.id))
                self.assertEqual({}, upgraded.delivery_plans_for([old.id]))
                with upgraded.connection() as conn:
                    self.assertEqual(11, conn.execute('PRAGMA user_version').fetchone()[0])
                    self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())
            finally:
                upgraded.close()


class InterviewDistillationTests(unittest.TestCase):
    def proposal(self, raw=None, note=None):
        raw = raw or answers()
        data = blueprint()
        data['user_distillation'] = [note or {'question_id': 'q07', 'summary': 'books'}]
        return validated_character_draft(json.dumps(data), raw, 'en-US')

    def test_unknown_unanswered_questions_are_absent_even_from_question_meanings(self):
        raw = {**answers(), 'q14': '__unsure__', 'q15': '', 'q16': None}
        prompt = character_generation_prompt(raw)
        data = json.loads(prompt.split('INTERVIEW DATA:\n')[1])
        for section in ['user_information', 'desired_character', 'question_meanings']:
            self.assertFalse({'q14', 'q15', 'q16'} & set(data[section]))

    def test_one_generation_returns_both_character_and_profile_without_implicit_save(self):
        provider = SyntheticCharacterProvider()
        provider.blueprint = {**blueprint(), 'user_distillation': [{'question_id': 'q07', 'summary': 'books'}]}
        with CompanionCore(':memory:', provider=provider, learning_enabled=False) as core:
            result = core.generate_character(answers(), 'en-US')
            self.assertEqual(1, provider.calls)
            self.assertEqual('books', result['user_distillation'][0]['summary'])
            self.assertEqual([], core.aul()['profile']['interests'])

    def test_confirmation_is_idempotent_keeps_raw_answers_and_preserves_later_corrections(self):
        raw = {**answers(), 'q06': 'I study mathematics throughout most weekdays'}
        proposal = self.proposal(raw, {'question_id': 'q06', 'summary': 'math student'})
        with CompanionCore(':memory:', learning_enabled=False) as core:
            core.onboarding.submit(raw, True)
            source = core.store.save_message('default', 'user', 'Synthetic later correction', learning_status='disabled')
            core.store.save_evidence([Evidence(id='synthetic_ev', type='profile_fact', key='profile.job', value='designer',
                source_message_id=source.id, confidence=.99, signal='correction')])
            core.learning.aggregator.aggregate()
            before = core.aul()['profile']['job']['value']
            distilled = core.onboarding.apply_distillation(proposal)
            self.assertEqual(before, distilled['profile']['job']['value'])
            self.assertEqual(raw, core.onboarding.status()['answers'])
            version = core.aul()['version']
            core.onboarding.apply_distillation(proposal)
            self.assertEqual(version, core.aul()['version'])

    def test_stale_draft_rollback_and_answer_withdrawal(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            core.onboarding.submit(answers(), True)
            proposal = self.proposal()
            core.onboarding.submit({'q07': 'astronomy'})
            with self.assertRaises(ValueError):
                core.onboarding.apply_distillation(proposal)
            self.assertNotIn('books', str(core.aul()['profile']['interests']))
            fresh = self.proposal({**answers(), 'q07': 'astronomy'}, {'question_id': 'q07', 'summary': 'stars'})
            core.onboarding.apply_distillation(fresh)
            self.assertIn('stars', str(core.aul()['profile']['interests']))
            core.onboarding.submit({'q07': None})
            self.assertEqual([], core.aul()['profile']['interests'])

    def test_reject_unanswered_role_numeric_or_duplicate_notes_and_changed_identifiers(self):
        for notes in [[{'question_id': 'q14', 'summary': 'invented'}], [{'question_id': 'q36', 'summary': 'role'}],
                      [{'question_id': 'q21', 'summary': 'style'}], [{'question_id': 'q01', 'summary': 'changed name'}],
                      [{'question_id': 'q07', 'summary': 'books'}]*2]:
            data = {**blueprint(), 'user_distillation': notes}
            with self.assertRaises(ValueError):
                validated_character_draft(json.dumps(data), answers(), 'en-US')
        raw = {**answers(), 'q10': 'exam ends at 15:30'}
        with self.assertRaises(ValueError):
            self.proposal(raw, {'question_id': 'q10', 'summary': 'exam at 14:00'})
        with self.assertRaises(ValueError):
            self.proposal({**answers(), 'q07': '不要聊咖啡'}, {'question_id': 'q07', 'summary': '咖啡'})
        with self.assertRaises(ValueError):
            self.proposal(answers(), {'question_id': 'q19', 'summary': 'guilt allowed'})

    def test_hot_context_never_contains_full_questionnaire_and_pressure_archives_without_api(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            self.assertEqual(5400, core.context_budget)
            self.assertEqual(5400, core.memory.token_threshold)
            raw = {**answers(), 'q14': 'UNANSWERED_ORIGINAL_NOT_FOR_HOT_PROMPT'}
            core.onboarding.submit(raw, True)
            policy = core.current_policy('随便聊聊')
            context = core.context_builder.build(core.aul(), policy, 'hi', [], [], 5400)
            self.assertNotIn('question_meanings', compile_dialogue_prompt(context))
            self.assertNotIn('onboarding_answers', compile_dialogue_prompt(context))
            for i in range(4):
                core.store.save_message('pressure', 'user', '旧话题'*500, learning_status='disabled')
            with patch.object(core.provider, 'generate', side_effect=AssertionError('no summary model')):
                self.assertIsNotNone(core.memory.maybe_create_rolling_summary('pressure'))
            self.assertEqual(4, core.store.count_messages('pressure'))


if __name__ == '__main__':
    unittest.main()
