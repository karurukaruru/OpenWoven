from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.context import estimate_tokens
from adaptive_companion.core import CompanionCore
from adaptive_companion.llm import LLMProvider, OpenAICompatibleProvider, compile_dialogue_prompt
from adaptive_companion.observer import RuleBasedObserver


class FailingObserver(RuleBasedObserver):
    def observe(self, message):
        raise ValueError('synthetic learning error')


class MalformedUsageProvider(LLMProvider):
    last_usage = {'prompt_tokens': float('inf'), 'completion_tokens': float('nan')}
    def generate(self, context):
        return 'synthetic offline answer'


class FinalReviewTests(unittest.TestCase):
    def test_client_message_id_is_shared_by_pending_saved_and_deleted_message(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            result = core.chat_result('synthetic message', message_id='msg_client_known')
            self.assertEqual('msg_client_known', result['user_message_id'])
            self.assertIsNotNone(core.store.get_message('msg_client_known'))
            core.delete_message('msg_client_known')
            self.assertEqual([], core.store.list_messages())

    def test_late_reply_cannot_recreate_a_deleted_client_identified_message(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            def delete_during_generation(context):
                self.assertEqual('pending', core.store.get_message('msg_client_known').status)
                core.delete_message('msg_client_known')
                return 'late synthetic answer'
            with patch.object(core.provider, 'generate', side_effect=delete_during_generation):
                with self.assertRaises(ValueError):
                    core.chat_result('synthetic message', message_id='msg_client_known')
            self.assertEqual([], core.store.list_messages())

    def test_duplicate_client_id_never_overwrites_another_message(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            core.store.save_message('default', 'user', 'first', message_id='msg_client_known')
            import sqlite3
            with self.assertRaises(sqlite3.IntegrityError):
                core.store.save_message('default', 'user', 'second', message_id='msg_client_known')
            self.assertEqual('first', core.store.get_message('msg_client_known').content)

    def test_malformed_usage_does_not_turn_a_successful_answer_into_a_failure(self):
        for usage in ({'prompt_tokens': float('inf'), 'completion_tokens': float('nan')}, 'invalid', [3], True):
            provider = MalformedUsageProvider()
            provider.last_usage = usage
            with CompanionCore(':memory:', provider=provider, learning_enabled=False) as core:
                self.assertEqual('synthetic offline answer', core.chat('hello'))
                self.assertEqual('estimated', core.store.list_generation_metrics()[0]['usage_source'])
        provider = OpenAICompatibleProvider('https://example.invalid', '', 'synthetic')
        provider._record_usage({'prompt_tokens': float('nan'), 'completion_tokens': -1, 'total_tokens': 9, 'other': 2})
        self.assertEqual({'total_tokens': 9}, provider.last_usage)

    def test_invalid_manual_baselines_do_not_become_extreme_preferences(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            for value in (True, float('inf'), float('-inf'), float('nan')):
                with self.assertRaises(ValueError):
                    core.set_preference_baseline('reply_length', value)
            self.assertEqual([], core.store.list_evidence())

    def test_resaving_unchanged_answers_preserves_later_feedback(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            core.onboarding.submit({'q01': 'user', 'q21': .8})
            reply = core.chat_result('hello')
            core.submit_feedback(reply['assistant_message_id'], 'too_long')
            before = core.aul()['interaction']['reply_length']
            ids = {item.id for item in core.store.list_evidence()}
            core.onboarding.submit({'q01': 'user', 'q21': .8, 'q36': 'calm'})
            self.assertEqual(before, core.aul()['interaction']['reply_length'])
            self.assertEqual(ids, {item.id for item in core.store.list_evidence()})

    def test_duplicate_draft_does_not_write_evidence_messages_or_aul_version(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            core.onboarding.submit({'q01': 'user', 'q21': .8})
            before = core.aul()
            messages = core.store.count_messages()
            core.onboarding.submit({'q01': ' user ', 'q21': '0.8'})
            self.assertEqual(messages, core.store.count_messages())
            self.assertEqual(before, core.aul())

    def test_changed_answer_still_overrides_old_baseline(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            core.onboarding.submit({'q21': .8})
            core.onboarding.submit({'q21': .2})
            self.assertEqual(.2, core.aul()['interaction']['reply_length']['value'])
            self.assertEqual(1, len(core.store.list_evidence()))
            core.onboarding.submit({'q21': None})
            self.assertEqual([], core.store.list_evidence())

    def test_full_cursor_survives_restart_and_skipped_optional_questions(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'resume.db'
            with CompanionCore(db, learning_enabled=False) as core:
                core.onboarding.submit({'q01': 'user'}, progress={'full_interview': True, 'resume_index': 30})
                core.onboarding.submit({'q01': 'user'}, progress={'full_interview': True, 'resume_index': 35})
            with CompanionCore(db, learning_enabled=False) as core:
                status = core.onboarding.status()
                self.assertEqual(35, status['resume_index'])
                self.assertNotEqual(35, status['next_index'])
                self.assertTrue(status['full_interview'])

    def test_invalid_cursor_is_ignored_and_finished_mode_is_recorded(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            core.onboarding.submit({}, progress={'full_interview': 'true', 'resume_index': -1})
            self.assertEqual(0, core.onboarding.status()['resume_index'])
            self.assertFalse(core.onboarding.status()['full_interview'])
            core.onboarding.submit({}, progress={'full_interview': True, 'resume_index': True})
            core.onboarding.submit({}, finish=True)
            self.assertEqual(50, core.onboarding.status()['resume_index'])

    def test_draft_progress_rolls_back_with_answer_evidence(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            core.onboarding.submit({'q01': 'first'}, progress={'resume_index': 5})
            before = core.onboarding.status()
            with patch.object(core.learning.aggregator, 'aggregate', side_effect=ValueError('synthetic crash')):
                with self.assertRaises(ValueError):
                    core.onboarding.submit({'q01': 'changed'}, progress={'full_interview': True, 'resume_index': 30})
            self.assertEqual(before, core.onboarding.status())

    def test_real_rendered_prompt_is_counted_and_empty_memory_reserve_is_reused(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            recent = [core.store.save_message('default', 'user', '测试内容' * 20) for _ in range(30)]
            query = 'continue'
            context = core.context_builder.build(core.aul(), core.current_policy(query), query, recent, [], 900)
            actual = estimate_tokens(compile_dialogue_prompt(context)) + estimate_tokens(query)
            self.assertEqual(actual, context['estimated_tokens'])
            self.assertLessEqual(actual, 900)
            self.assertEqual(0, context['budget_allocation']['memory'])
            count = len(context['recent_conversation'])
            self.assertGreater(count, 0)
            self.assertLess(count, len(recent))
            one_more = copy.deepcopy(context)
            message = recent[-count-1]
            one_more['recent_conversation'].insert(0, {'role': message.role, 'content': message.content})
            self.assertGreater(estimate_tokens(compile_dialogue_prompt(one_more)) + estimate_tokens(query), 900)

    def test_mandatory_sections_are_preserved_even_if_budget_is_too_small(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            context = core.context_builder.build(core.aul(), core.current_policy('hi'), 'hi', [], [], 10)
            self.assertGreater(context['estimated_tokens'], 10)
            self.assertEqual('hi', context['current_user_message'])
            self.assertTrue(context['persona'])

    def test_bridge_failure_does_not_keep_a_closed_core_as_initialized(self):
        with tempfile.TemporaryDirectory() as folder, patch('urllib.request.urlopen', side_effect=AssertionError('no network')):
            try:
                db = str(Path(folder) / 'bridge.db')
                android_bridge.initialize(db, '{}')
                with self.assertRaises(ValueError):
                    android_bridge.initialize(db, json.dumps({'learning': {'weak_rate': 'invalid'}}))
                with self.assertRaises(RuntimeError):
                    android_bridge.get_aul()
                android_bridge.initialize(db, '{}')
                self.assertIn('version', json.loads(android_bridge.get_aul()))
            finally:
                android_bridge.close()

    def test_bad_config_shape_does_not_destroy_a_valid_core(self):
        try:
            android_bridge.initialize(':memory:', '{}')
            before = android_bridge.get_aul()
            for config in ('[]', '{"provider":[]}'):
                with self.assertRaises(ValueError):
                    android_bridge.initialize(':memory:', config)
                self.assertEqual(before, android_bridge.get_aul())
        finally:
            android_bridge.close()

    def test_privacy_reset_drains_failed_learning_instead_of_refusing_deletion(self):
        try:
            android_bridge.initialize(':memory:', '{}')
            core = android_bridge._require_core()
            core.learning.observer = FailingObserver()
            message = core.store.save_message('default', 'user', 'synthetic private message')
            future = core.learning.submit(message.id)
            with self.assertRaises(ValueError):
                future.result(timeout=5)
            android_bridge.clear_user_data()
            self.assertEqual([], core.store.list_messages())
            self.assertEqual([], core.store.list_evidence())
            self.assertEqual(0, core.aul()['relationship']['interaction_count'])
        finally:
            android_bridge.close()


if __name__ == '__main__':
    unittest.main()
