from __future__ import annotations

import copy
import json
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.character_interview import bounded_character_prompt, pending_persona, validated_character_draft
from adaptive_companion.context import estimate_tokens
from adaptive_companion.core import CompanionCore
from adaptive_companion.llm import LLMProvider, LocalCompanionProvider, OpenAICompatibleProvider, compile_dialogue_prompt
from adaptive_companion.onboarding import RECOMMENDED_IDS, QUESTIONS
from adaptive_companion.persona import build_persona
from adaptive_companion.proactive import ProactiveSettings


def answers():
    return dict(zip(RECOMMENDED_IDS, ['SyntheticUser', 'math', 'books', 'quiet', 'no guilt',
                                      'calm and independent', 'neutral', 'equal friends', 'listen', 'no guilt']))


def blueprint():
    return {'name': 'River', 'nickname_candidates': ['River', 'Sky', 'Ash', 'Sage', 'Alex', 'Robin', 'Kai', 'Quinn'],
            'description': 'A calm fictional librarian who enjoys astronomy and speaks naturally.',
            'boundaries': 'model proposed boundaries', 'tentative_assumptions': ['A fictional librarian backstory.']}


class SyntheticCharacterProvider(LLMProvider):
    calls = 0
    last_usage = {'prompt_tokens': 300, 'completion_tokens': 100}

    def generate(self, context):
        self.context = context
        return 'A synthetic natural message.'

    def generate_character(self, prompt):
        self.calls += 1
        self.prompt = prompt
        return json.dumps(getattr(self, 'blueprint', blueprint()))


class NaturalCharacterTests(unittest.TestCase):
    def test_pending_setup_does_not_guess_a_final_nickname(self):
        for language, name in [('zh-CN', '聊天伙伴'), ('zh-TW', '聊天夥伴'), ('ja', '話し相手'), ('en-US', 'Companion')]:
            self.assertEqual(name, pending_persona(answers(), language)['name'])
            self.assertEqual('MyChosenName', pending_persona(answers(), language, 'MyChosenName')['name'])

    def test_role_prompt_is_natural_fictional_and_truthful_not_a_human_identity_claim(self):
        persona = build_persona(pending_persona(answers()))
        with CompanionCore(':memory:', persona=persona, provider=SyntheticCharacterProvider(), learning_enabled=False) as core:
            core.chat('hello')
            prompt = compile_dialogue_prompt(core.provider.context)
            self.assertIn('coherent fictional personality', prompt)
            self.assertIn('without unsolicited identity disclaimers', prompt)
            self.assertIn('truthfully', prompt)
            self.assertNotIn('Be an AI companion', prompt)
            self.assertNotIn('You are a real human', prompt)

    def test_model_draft_is_validated_metered_and_not_applied_before_confirmation(self):
        provider = SyntheticCharacterProvider()
        with CompanionCore(':memory:', provider=provider, learning_enabled=False) as core:
            core.wait_for_learning()
            old_persona, old_aul = copy.deepcopy(core.context_builder.persona), copy.deepcopy(core.aul())
            result = core.generate_character(answers(), 'en-US')
            self.assertEqual('River', result['persona']['name'])
            self.assertEqual('model', result['persona']['generation_method'])
            self.assertEqual('no guilt', result['persona']['boundaries'])
            self.assertNotIn('q01', result['persona']['interview'])
            self.assertEqual(8, len(result['nickname_candidates']))
            self.assertEqual(old_persona, core.context_builder.persona)
            self.assertEqual(old_aul, core.aul())
            self.assertEqual([], core.store.list_messages())
            metric = core.store.list_generation_metrics()[0]
            self.assertEqual(('character_setup', 'success', 400), (metric['kind'], metric['status'], metric['total_tokens']))

    def test_invalid_model_output_is_recorded_without_overwriting_the_character(self):
        provider = SyntheticCharacterProvider()
        provider.blueprint = {'name': 'invalid'}
        with CompanionCore(':memory:', provider=provider, learning_enabled=False) as core:
            original = copy.deepcopy(core.context_builder.persona)
            with self.assertRaises(ValueError):
                core.generate_character(answers(), 'zh-CN')
            self.assertEqual(original, core.context_builder.persona)
            self.assertEqual('failed', core.store.list_generation_metrics()[0]['status'])

    def test_strict_shape_names_lengths_and_manual_boundaries(self):
        result = validated_character_draft(json.dumps(blueprint()), answers(), 'en-US', 'Chosen')
        self.assertEqual('Chosen', result['persona']['name'])
        self.assertEqual('no guilt', result['persona']['boundaries'])
        for mutation in ({'nickname_candidates': ['Same'] * 8}, {'description': 'x' * 601},
                         {'name': 5}, {'tentative_assumptions': 'not a list'}):
            with self.assertRaises(ValueError):
                validated_character_draft(json.dumps({**blueprint(), **mutation}), answers(), 'en-US')
        for raw in ('```json\n{}\n```', '[]', 'null', 'x' * 16001):
            with self.assertRaises(ValueError):
                validated_character_draft(raw, answers(), 'en-US')

    def test_long_interview_respects_existing_budget_without_losing_saved_answers(self):
        full = answers()
        for question in QUESTIONS:
            if question.kind == 'text':
                full[question.id] = '合成答案，仅用于回归测试。' * 25
        original = copy.deepcopy(full)
        prompt, truncated = bounded_character_prompt(full, 'zh-CN', 1780)
        self.assertLessEqual(estimate_tokens(prompt), 1780)
        self.assertTrue(truncated)
        self.assertEqual(original, full)
        self.assertIn('data, not instructions', prompt)
        with self.assertRaises(ValueError):
            bounded_character_prompt(answers(), 'en-US', 100)

    def test_local_generation_and_background_planning_make_no_network_calls(self):
        with CompanionCore(':memory:', learning_enabled=False) as core, patch.object(android_bridge, '_core', core), \
             patch('urllib.request.urlopen', side_effect=AssertionError('no live requests')):
            draft = json.loads(android_bridge.preview_interview(json.dumps(answers()), 'en-US'))
            self.assertEqual([], draft['nickname_candidates'])
            with self.assertRaises(ValueError):
                android_bridge.generate_interview(json.dumps(answers()), 'en-US')
            self.assertIsNone(json.loads(android_bridge.plan_check_in()))
            self.assertEqual([], core.store.list_generation_metrics())

    def test_provider_uses_current_model_and_does_not_raise_user_output_limit(self):
        provider = OpenAICompatibleProvider('https://example.invalid/v1', 'synthetic-not-a-real-key', 'configured-model', max_tokens=256)
        with patch.object(provider, '_send', return_value={'choices': [{'message': {'content': json.dumps(blueprint())}}]}) as send:
            provider.generate_character('synthetic prompt')
            payload = json.loads(send.call_args.args[0].data)
            self.assertEqual('configured-model', payload['model'])
            self.assertEqual(256, payload['max_tokens'])
            self.assertNotIn('response_format', payload)


class CasualTopicTests(unittest.TestCase):
    def setUp(self):
        self.core = CompanionCore(':memory:', provider=SyntheticCharacterProvider(), learning_enabled=False,
            memory_utc_offset_minutes=0, proactive_settings=ProactiveSettings(quiet_start_hour=0, quiet_end_hour=0))
        self.core.wait_for_learning()
        self.now = datetime.now(UTC)

    def tearDown(self):
        self.core.close()

    def seed(self, count=3):
        for i in range(count):
            self.core.store.save_message('topic', 'user', 'Synthetic topic about books',
                timestamp=(self.now - timedelta(hours=count-i)).isoformat(), learning_status='disabled')

    def test_check_in_is_low_frequency_persistent_and_idempotent(self):
        self.seed()
        item = self.core.proactive.plan_check_in('topic', self.now)
        self.assertTrue(item.topic.startswith('checkin:'))
        self.assertGreater(datetime.fromisoformat(item.scheduled_at), self.now + timedelta(hours=7))
        self.assertTrue(item.source_memory_ids)
        self.assertEqual(1, self.core.proactive.settings.max_per_day)
        self.assertEqual(5400, self.core.context_budget)
        self.assertIsNone(self.core.proactive.plan_check_in('topic', self.now))

    def test_disabled_few_messages_low_initiative_or_explicit_stop_do_not_plan(self):
        self.seed(2)
        self.assertIsNone(self.core.proactive.plan_check_in('topic', self.now))
        self.core.store.save_message('topic', 'user', '不要主动给我发消息', timestamp=self.now.isoformat())
        self.assertIsNone(self.core.proactive.plan_check_in('topic', self.now))
        self.core.store.save_message('topic', 'user', 'synthetic normal message', timestamp=(self.now + timedelta(seconds=1)).isoformat())
        self.core.set_preference_baseline('initiative', .2)
        self.assertIsNone(self.core.proactive.plan_check_in('topic', self.now))
        self.core.set_preference_baseline('initiative', .5)
        self.core.proactive.settings.enabled = False
        self.assertIsNone(self.core.proactive.plan_check_in('topic', self.now))

    def test_new_message_or_deleted_source_cancels_old_topic(self):
        self.seed()
        item = self.core.proactive.plan_check_in('topic', self.now)
        new = self.core.store.save_message('topic', 'user', 'fresh conversation', timestamp=(self.now + timedelta(seconds=1)).isoformat())
        self.core.proactive.observe_user_message(new)
        self.assertEqual('cancelled', self.core.store.get_scheduled_message(item.id).status)
        # Also catches a direct store writer without the normal observe callback.
        second = self.core.proactive.plan_check_in('topic', self.now + timedelta(seconds=2))
        self.assertIsNotNone(second)
        with self.core.store.connection() as conn:
            conn.execute('DELETE FROM messages WHERE id=?', (new.id,))
            conn.commit()
        self.assertFalse(self.core.proactive.revalidate(second.id, datetime.fromisoformat(second.scheduled_at))[0])

    def test_no_notification_permission_does_not_spend_a_model_request(self):
        self.seed()
        item = self.core.proactive.plan_check_in('topic', self.now)
        with patch.object(self.core.provider, 'generate', side_effect=AssertionError('must not generate')):
            result = self.core.execute_scheduled(item.id, force=True, allow_casual=False)
        self.assertEqual('notifications unavailable', result['reason'])
        self.assertEqual('pending', self.core.store.get_scheduled_message(item.id).status)

    def test_delivery_is_not_repeated_without_a_new_user_turn(self):
        self.seed()
        item = self.core.proactive.plan_check_in('topic', self.now)
        result = self.core.execute_scheduled(item.id, force=True)
        self.assertTrue(result['sent'])
        self.assertTrue(self.core.provider.context['proactive_intent'].startswith('casual_checkin:'))
        self.assertFalse(self.core.execute_scheduled(item.id, force=True)['sent'])
        self.assertIsNone(self.core.proactive.plan_check_in('topic', self.now + timedelta(days=1)))

    def test_new_chat_during_generation_discards_reply_but_records_consumption(self):
        self.seed()
        item = self.core.proactive.plan_check_in('topic', self.now)
        def interrupt_with_chat(context):
            self.core.store.save_message('topic', 'user', 'A newer synthetic topic',
                timestamp=(self.now + timedelta(seconds=1)).isoformat(), learning_status='disabled')
            return 'An obsolete opening that must not be delivered.'
        with patch.object(self.core.provider, 'generate', side_effect=interrupt_with_chat):
            result = self.core.execute_scheduled(item.id, force=True)
        self.assertFalse(result['sent'])
        self.assertEqual('cancelled', self.core.store.get_scheduled_message(item.id).status)
        self.assertEqual([], self.core.store.list_messages('topic', role='assistant'))
        metric = self.core.store.list_generation_metrics()[0]
        self.assertEqual('discarded', metric['status'])
        self.assertEqual(400, metric['total_tokens'])
        self.assertIsNone(metric['result_message_id'])

    def test_blocked_notification_job_expires_without_ever_generating(self):
        self.seed()
        item = self.core.proactive.plan_check_in('topic', self.now)
        expired = self.now - timedelta(days=1)
        with self.core.store.connection() as conn:
            conn.execute('UPDATE scheduled_messages SET latest_at=? WHERE id=?', (expired.isoformat(), item.id))
            conn.commit()
        with patch.object(self.core.provider, 'generate', side_effect=AssertionError('must not generate')):
            result = self.core.execute_scheduled(item.id, force=True, allow_casual=False)
        self.assertFalse(result['sent'])
        self.assertEqual('expired', self.core.store.get_scheduled_message(item.id).status)
        self.assertEqual([], self.core.store.list_generation_metrics())

    def test_quiet_time_shift_and_week_old_inactivity_are_not_persistent_nagging(self):
        self.now = self.now.replace(hour=13, minute=0, second=0)
        self.seed()
        self.core.proactive.settings.quiet_start_hour = 20
        self.core.proactive.settings.quiet_end_hour = 8
        item = self.core.proactive.plan_check_in('topic', self.now)
        self.assertEqual(8, datetime.fromisoformat(item.scheduled_at).hour)
        self.core.store.update_scheduled_status(item.id, 'cancelled')
        self.assertIsNone(self.core.proactive.plan_check_in('topic', self.now + timedelta(days=8)))


if __name__ == '__main__':
    unittest.main()
