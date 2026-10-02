from __future__ import annotations

import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.core import CompanionCore
from adaptive_companion.llm import LLMProvider
from adaptive_companion.observer import RuleBasedObserver
from adaptive_companion.proactive import ProactiveSettings
from adaptive_companion.turns import composer_gate


class OfflineProvider(LLMProvider):
    def __init__(self):
        self.contexts = []

    def generate(self, context):
        self.contexts.append(context)
        return '好呀\n慢慢来'


class TurnLifecycleReviewTests(unittest.TestCase):
    def setUp(self):
        composer_gate.states.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.core = CompanionCore(self.root / 'review.db', provider=OfflineProvider(),
            learning_enabled=False, summary_message_threshold=2,
            proactive_settings=ProactiveSettings(enabled=False),
            attachment_root=str(self.root), supports_vision=True)

    def tearDown(self):
        self.core.close()
        android_bridge.close()
        composer_gate.states.clear()
        self.tmp.cleanup()

    def test_queued_reply_triggers_rolling_memory_without_observer(self):
        turn = self.core.queue_user_turn('今天我在准备高数考试')
        self.core.execute_scheduled(turn['scheduled_message'], force=True)
        self.core.wait_for_learning()
        memories = self.core.store.list_memories('rolling')
        self.assertEqual(1, len(memories))
        self.assertIsNotNone(self.core.store.get_metadata('rolling_last:default'))

    def test_retry_triggers_rolling_memory(self):
        turn = self.core.queue_user_turn('最近我正在学习吉他和乐理')
        self.core.retry_message(turn['user_message_id'])
        self.core.wait_for_learning()
        self.assertEqual(1, len(self.core.store.list_memories('rolling')))

    def test_late_learning_completion_retries_deferred_summary(self):
        entered, release = threading.Event(), threading.Event()

        class SlowOfflineObserver(RuleBasedObserver):
            def observe(self, message):
                entered.set()
                if not release.wait(10):
                    raise RuntimeError('offline test timed out')
                return super().observe(message)

        self.core.close()
        self.core = CompanionCore(self.root / 'late.db', provider=OfflineProvider(),
            observer=SlowOfflineObserver(), summary_message_threshold=2,
            proactive_settings=ProactiveSettings(enabled=False))
        try:
            turn = self.core.queue_user_turn('我最近正在认真学习日语')
            self.assertTrue(entered.wait(3))
            self.core.execute_scheduled(turn['scheduled_message'], force=True)
            self.assertEqual([], self.core.store.list_memories('rolling'))
        finally:
            release.set()
        self.core.wait_for_learning()
        self.assertEqual(1, len(self.core.store.list_memories('rolling')))

    def test_explicit_zero_length_is_not_an_unanswered_question(self):
        android_bridge.initialize(str(self.root / 'zero.db'), json.dumps({
            'persona': {'interview': {'q21': 0}}, 'daily_reply_length': .8,
            'learning': {'enabled': False}}))
        self.assertEqual(0, android_bridge._require_core().context_builder.persona['initial_style']['reply_length'])

    def test_unsure_length_uses_daily_default(self):
        android_bridge.initialize(str(self.root / 'unsure.db'), json.dumps({
            'persona': {'interview': {'q21': '__unsure__'}}, 'daily_reply_length': .8,
            'learning': {'enabled': False}}))
        self.assertEqual(.8, android_bridge._require_core().context_builder.persona['initial_style']['reply_length'])

    def test_failed_generation_marks_every_bubble_retryable(self):
        first = self.core.queue_user_turn('第一句')
        last = self.core.queue_user_turn('第二句')
        with patch.object(self.core.provider, 'generate', side_effect=RuntimeError('offline failure')):
            with self.assertRaises(RuntimeError):
                self.core.execute_scheduled(last['scheduled_message'], force=True)
        for turn in (first, last):
            self.assertEqual('failed', self.core.store.get_message(turn['user_message_id']).status)

    def test_vision_validation_failure_never_leaves_sending_status(self):
        image = self.root / 'offline.jpg'
        image.write_bytes(b'\xff\xd8\xffsynthetic-fixture')
        first = self.core.queue_user_turn('第一张', image_path=str(image))
        last = self.core.queue_user_turn('再解释一下')
        self.core.supports_vision = False
        with self.assertRaisesRegex(ValueError, 'support images'):
            self.core.retry_message(first['user_message_id'])
        for turn in (first, last):
            self.assertEqual('failed', self.core.store.get_message(turn['user_message_id']).status)

    def test_retry_commits_all_source_statuses_in_one_transaction(self):
        first = self.core.queue_user_turn('第一句')
        self.core.queue_user_turn('第二句')
        original = self.core.store.update_message_status

        def reject_separate_completion(message_id, status, error=None):
            if status == 'sent':
                raise AssertionError('completion must belong to the reply transaction')
            return original(message_id, status, error)

        with patch.object(self.core.store, 'update_message_status', side_effect=reject_separate_completion):
            self.core.retry_message(first['user_message_id'])
        self.assertTrue(all(m.status == 'sent' for m in self.core.store.list_messages(role='user')))

    def test_atomic_retry_completion_rolls_back_all_bubbles_with_reply(self):
        first = self.core.queue_user_turn('第一句')
        last = self.core.queue_user_turn('第二句')
        with patch.object(self.core.store, '_write_delivery_plan', side_effect=RuntimeError('offline write failure')):
            with self.assertRaises(RuntimeError):
                self.core.store.complete_reply(last['user_message_id'], '测试回复', {},
                    source_message_ids=[first['user_message_id'], last['user_message_id']])
        self.assertEqual(0, self.core.store.count_messages(role='assistant'))
        self.assertTrue(all(m.status == 'waiting' for m in self.core.store.list_messages(role='user')))

    def test_queued_context_uses_budget_instead_of_only_eight_prior_bubbles(self):
        for index in range(20):
            self.core.store.save_message('default', 'user' if index % 2 == 0 else 'assistant',
                f'上一段对话 {index}', learning_status='disabled')
        turn = self.core.queue_user_turn('继续我们刚才的话题')
        self.core.execute_scheduled(turn['scheduled_message'], force=True)
        context = self.core.provider.contexts[-1]
        self.assertEqual(20, len(context['recent_conversation']))
        self.assertNotIn('继续我们刚才的话题', [m['content'] for m in context['recent_conversation']])
        self.assertLessEqual(context['estimated_tokens'], 5400)

    def test_delivery_does_not_wait_for_database_while_holding_input_gate(self):
        turn = self.core.queue_user_turn('检查输入状态和归档的锁顺序')
        self.core.wait_for_learning()
        state = threading.local()
        gate, connection = composer_gate.lock, self.core.store.connection

        class TrackedGate:
            def __enter__(self):
                gate.acquire()
                state.gate_depth = getattr(state, 'gate_depth', 0) + 1

            def __exit__(self, *args):
                state.gate_depth -= 1
                gate.release()

        @contextmanager
        def checked_connection():
            depth = getattr(state, 'database_depth', 0)
            if depth == 0:
                self.assertEqual(0, getattr(state, 'gate_depth', 0))
            state.database_depth = depth + 1
            try:
                with connection() as conn:
                    yield conn
            finally:
                state.database_depth -= 1

        with patch.object(composer_gate, 'lock', TrackedGate()), patch.object(self.core.store, 'connection', checked_connection):
            self.assertTrue(self.core.execute_scheduled(turn['scheduled_message'], force=True)['sent'])
            self.core.wait_for_learning()
