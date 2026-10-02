import json
import unittest
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.core import CompanionCore
from adaptive_companion.llm import LLMProvider
from adaptive_companion.proactive import ProactiveSettings
from adaptive_companion.turns import composer_gate


class HeldOfflineProvider(LLMProvider):
    def __init__(self):
        self.calls = 0
        self.hold = False

    def generate(self, context):
        self.calls += 1
        if self.hold:
            composer_gate.note('default', True)
        return '好呀\n慢慢来'


class DeletedScheduleReviewTests(unittest.TestCase):
    def setUp(self):
        composer_gate.states.clear()
        self.provider = HeldOfflineProvider()
        self.core = CompanionCore(':memory:', provider=self.provider, learning_enabled=False,
            proactive_settings=ProactiveSettings(enabled=False))

    def tearDown(self):
        self.core.close()
        composer_gate.states.clear()

    def test_deleting_held_task_discards_paid_cache_and_settles_all_sent_bubbles(self):
        first = self.core.queue_user_turn('第一句')
        second = self.core.queue_user_turn('还有一句')
        self.provider.hold = True
        result = self.core.execute_scheduled(second['scheduled_message'], force=True)
        self.assertFalse(result['sent'])
        key = 'turn_reply:' + second['scheduled_message']
        self.assertIsNotNone(self.core.store.get_metadata(key))
        with patch.object(android_bridge, '_core', self.core):
            self.assertTrue(json.loads(android_bridge.delete_scheduled(second['scheduled_message']))['deleted'])
        self.assertIsNone(self.core.store.get_metadata(key))
        self.assertIsNone(self.core.store.get_scheduled_message(second['scheduled_message']))
        for source in (first, second):
            self.assertEqual('failed', self.core.store.get_message(source['user_message_id']).status)
        metrics = self.core.store.list_generation_metrics()
        self.assertEqual(1, len(metrics))
        self.assertEqual('discarded', metrics[0]['status'])
        self.assertEqual(1, self.provider.calls)
        self.assertEqual(0, self.core.store.count_messages(role='assistant'))

    def test_deleting_pending_batch_does_not_leave_earlier_bubble_waiting(self):
        first = self.core.queue_user_turn('第一句')
        last = self.core.queue_user_turn('第二句')
        with patch.object(android_bridge, '_core', self.core):
            android_bridge.delete_scheduled(last['scheduled_message'])
        self.assertEqual(['failed', 'failed'], [self.core.store.get_message(t['user_message_id']).status for t in (first, last)])
        self.assertEqual(0, self.provider.calls)

    def test_repeated_task_deletion_is_idempotent_without_double_cost_accounting(self):
        turn = self.core.queue_user_turn('缓存测试')
        self.provider.hold = True
        self.core.execute_scheduled(turn['scheduled_message'], force=True)
        with patch.object(android_bridge, '_core', self.core):
            android_bridge.delete_scheduled(turn['scheduled_message'])
            android_bridge.delete_scheduled(turn['scheduled_message'])
        self.assertEqual(1, len(self.core.store.list_generation_metrics()))
        self.assertEqual(1, self.provider.calls)


if __name__ == '__main__':
    unittest.main()
