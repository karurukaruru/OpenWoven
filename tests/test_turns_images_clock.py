from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.core import CompanionCore
from adaptive_companion.delivery import DeliveryPlanner, DeliverySettings
from adaptive_companion.llm import LLMProvider, OpenAICompatibleProvider, compile_dialogue_prompt
from adaptive_companion.persona import build_persona
from adaptive_companion.proactive import ProactiveSettings
from adaptive_companion.turns import composer_gate


class SyntheticProvider(LLMProvider):
    def __init__(self):
        self.contexts = []
        self.action = None

    def generate(self, context):
        self.contexts.append(context)
        if self.action:
            self.action()
        return '好呀 明天见 我买了寿司'


class TurnImageClockTests(unittest.TestCase):
    def setUp(self):
        composer_gate.states.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.image = self.root / 'synthetic.jpg'
        self.image.write_bytes(b'\xff\xd8\xffsynthetic-offline-fixture')
        self.provider = SyntheticProvider()
        self.core = CompanionCore(self.root / 'synthetic.db', provider=self.provider,
            learning_enabled=False, supports_vision=True, attachment_root=str(self.root),
            proactive_settings=ProactiveSettings(enabled=False, quiet_start_hour=0, quiet_end_hour=0))

    def tearDown(self):
        self.core.close()
        composer_gate.states.clear()
        self.tmp.cleanup()

    def test_three_sent_bubbles_are_one_request_and_no_duplicate_prompt(self):
        one = self.core.queue_user_turn('今天我去吃饭')
        two = self.core.queue_user_turn('买了寿司')
        three = self.core.queue_user_turn('还有奶茶')
        self.assertEqual([], self.provider.contexts)
        self.assertEqual(1, len(self.core.store.list_scheduled_messages('pending')))
        self.assertEqual('cancelled', self.core.store.get_scheduled_message(one['scheduled_message']).status)
        result = self.core.execute_scheduled(three['scheduled_message'], force=True)
        self.assertTrue(result['sent'])
        self.assertEqual('今天我去吃饭\n买了寿司\n还有奶茶', self.provider.contexts[0]['current_user_message'])
        self.assertEqual([], self.provider.contexts[0]['recent_conversation'])
        self.assertEqual(['好呀', '明天见', '我买了寿司'], [x['text'] for x in result['delivery_plan']['parts']])
        self.assertTrue(all(self.core.store.get_message(item['user_message_id']).status == 'sent' for item in [one, two, three]))
        self.assertFalse(self.core.execute_scheduled(three['scheduled_message'], force=True)['sent'])
        self.assertEqual(1, len(self.provider.contexts))

    def test_tap_empty_composer_resets_wait_and_draft_blocks_indefinitely(self):
        job = self.core.queue_user_turn('测试')
        composer_gate.note('default', False)
        self.assertEqual('composer active', self.core.execute_scheduled(job['scheduled_message'], force=True)['reason'])
        with patch('adaptive_companion.turns.time.monotonic', return_value=10**20):
            composer_gate.note('default', True)
            self.assertFalse(composer_gate.idle('default', 20))
        self.assertEqual([], self.provider.contexts)

    def test_unfinished_draft_during_generation_holds_reply_and_reuses_call(self):
        job = self.core.queue_user_turn('你好')
        self.provider.action = lambda: composer_gate.note('default', True)
        result = self.core.execute_scheduled(job['scheduled_message'], force=True)
        self.assertFalse(result['sent'])
        self.assertEqual(0, self.core.store.count_messages(role='assistant'))
        self.assertTrue(self.core.store.get_metadata('turn_reply:' + job['scheduled_message']))
        self.provider.action = None
        composer_gate.states.clear()
        self.assertTrue(self.core.execute_scheduled(job['scheduled_message'], force=True)['sent'])
        self.assertEqual(1, len(self.provider.contexts))
        self.assertIsNone(self.core.store.get_metadata('turn_reply:' + job['scheduled_message']))

    def test_new_sent_message_discards_held_old_reply_and_batches_everything(self):
        first = self.core.queue_user_turn('你好')
        self.provider.action = lambda: composer_gate.note('default', True)
        self.core.execute_scheduled(first['scheduled_message'], force=True)
        second = self.core.queue_user_turn('我还没说完')
        composer_gate.states.clear()
        self.provider.action = None
        result = self.core.execute_scheduled(second['scheduled_message'], force=True)
        self.assertTrue(result['sent'])
        self.assertEqual('你好\n我还没说完', self.provider.contexts[-1]['current_user_message'])
        self.assertEqual(1, self.core.store.count_messages(role='assistant'))
        self.assertIsNone(self.core.store.get_metadata('turn_reply:' + first['scheduled_message']))
        self.assertIn('discarded', [m['status'] for m in self.core.store.list_generation_metrics()])

    def test_saved_task_recovers_after_core_restart(self):
        job = self.core.queue_user_turn('明天见')
        self.core.close()
        self.core = CompanionCore(self.root / 'synthetic.db', provider=self.provider, learning_enabled=False)
        self.assertTrue(self.core.execute_scheduled(job['scheduled_message'], force=True)['sent'])

    def test_retry_old_bubble_uses_the_whole_failed_turn(self):
        first = self.core.queue_user_turn('第一句')
        self.core.queue_user_turn('第二句')
        result = self.core.retry_message(first['user_message_id'])
        self.assertEqual('第一句\n第二句', self.provider.contexts[-1]['current_user_message'])
        self.assertTrue(all(m.status == 'sent' for m in self.core.store.list_messages() if m.role == 'user'))
        self.assertEqual('第二句', self.core.store.get_message(result['user_message_id']).content)

    def test_retry_selects_newer_batch_even_if_old_greeting_was_due_later(self):
        self.core.delivery.settings.greeting_delay_enabled = True
        first = self.core.queue_user_turn('在吗')
        second = self.core.queue_user_turn('我买了寿司')
        self.assertGreater(self.core.store.get_scheduled_message(first['scheduled_message']).scheduled_at,
                           self.core.store.get_scheduled_message(second['scheduled_message']).scheduled_at)
        self.core.retry_message(first['user_message_id'])
        self.assertEqual('在吗\n我买了寿司', self.provider.contexts[-1]['current_user_message'])

    def test_image_only_send_has_private_attachment_and_vision_payload(self):
        job = self.core.queue_user_turn('', image_path=str(self.image))
        result = self.core.execute_scheduled(job['scheduled_message'], force=True)
        context = self.provider.contexts[-1]
        self.assertTrue(result['sent'])
        self.assertTrue(context['current_images'][0].startswith('data:image/jpeg;base64,'))
        self.assertNotIn('base64', compile_dialogue_prompt(context))
        self.assertNotIn('synthetic.jpg', compile_dialogue_prompt(context))
        self.assertEqual('[Image]', self.core.store.get_message(job['user_message_id']).content)

    def test_text_only_model_rejects_image_before_saving(self):
        self.core.supports_vision = False
        with self.assertRaisesRegex(ValueError, 'support images'):
            self.core.queue_user_turn('图片', image_path=str(self.image))
        self.assertEqual(0, self.core.store.count_messages())

    def test_switch_to_text_only_model_never_sends_pending_image(self):
        job = self.core.queue_user_turn('看看这个', image_path=str(self.image))
        self.core.supports_vision = False
        with self.assertRaisesRegex(ValueError, 'support images'):
            self.core.execute_scheduled(job['scheduled_message'], force=True)
        self.assertEqual([], self.provider.contexts)

    def test_attachment_paths_cannot_escape_private_directory(self):
        with self.assertRaises(ValueError):
            self.core.attachments.checked(str(self.root.parent / 'other.jpg'))
        invalid = self.root / 'invalid.jpg'
        invalid.write_bytes(b'not-jpeg')
        with self.assertRaises(ValueError):
            self.core.attachments.checked(str(invalid))

    def test_fifth_queued_image_is_rejected_without_another_user_message(self):
        for i in range(4):
            self.core.queue_user_turn(str(i), image_path=str(self.image))
        with self.assertRaisesRegex(ValueError, 'four images'):
            self.core.queue_user_turn('fifth', image_path=str(self.image))
        self.assertEqual(4, self.core.store.count_messages())

    def test_deleting_image_message_removes_private_file_and_metadata(self):
        job = self.core.queue_user_turn('caption', image_path=str(self.image))
        self.core.delete_message(job['user_message_id'])
        self.assertFalse(self.image.exists())
        self.assertIsNone(self.core.attachments.path(job['user_message_id']))

    def test_provider_request_uses_content_blocks_only_for_image_turn(self):
        job = self.core.queue_user_turn('caption', image_path=str(self.image))
        self.core.execute_scheduled(job['scheduled_message'], force=True)
        context = self.provider.contexts[-1]
        provider = OpenAICompatibleProvider('https://synthetic.invalid/v1', 'not-a-key', 'synthetic')
        requests = []
        def fake(request):
            requests.append(json.loads(request.data))
            return {'choices': [{'message': {'content': 'synthetic'}}]}
        with patch.object(OpenAICompatibleProvider, '_send', side_effect=fake):
            provider.generate(context)
            provider.generate({key: value for key, value in context.items() if key != 'current_images'})
        content = requests[0]['messages'][-1]['content']
        self.assertEqual(['text', 'image_url'], [block['type'] for block in content])
        self.assertEqual('auto', content[1]['image_url']['detail'])
        self.assertIsInstance(requests[1]['messages'][-1]['content'], str)

    def test_actual_clock_is_dynamic_and_included_in_text_budget(self):
        self.core.context_builder.clock = lambda: '2026-10-01T23:59:00+08:00 [Asia/Hong_Kong]'
        self.core.chat_result('现在呢')
        self.assertIn('Asia/Hong_Kong', compile_dialogue_prompt(self.provider.contexts[-1]))
        self.core.context_builder.clock = lambda: '2026-10-02T00:01:00+08:00 [Asia/Hong_Kong]'
        self.core.chat_result('今天呢')
        self.assertIn('2026-10-02', compile_dialogue_prompt(self.provider.contexts[-1]))
        self.assertLessEqual(self.provider.contexts[-1]['estimated_tokens'], 5400)

    def test_bubbles_stay_separate_with_timing_off_and_latin_tokens_intact(self):
        planner = DeliveryPlanner(DeliverySettings(enabled=False))
        parts = planner.plan('今天不错 明天见 我用 Visual Studio Code', policy={'context': 'casual_chat'}).parts
        self.assertEqual(['今天不错', '明天见', '我用 Visual Studio Code'], [p.text for p in parts])
        self.assertTrue(all(p.delay_ms == 0 for p in parts))

    def test_default_character_is_brief_but_explicit_detail_is_preserved(self):
        self.assertEqual(.30, build_persona()['initial_style']['reply_length'])
        self.assertEqual(.75, build_persona({'choices': {'detail': 'detailed'}})['initial_style']['reply_length'])

    def test_message_attachment_and_replacement_task_roll_back_together(self):
        first = self.core.queue_user_turn('保留这一句')
        with patch.object(self.core.delayed_replies, 'enqueue_turn', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.core.queue_user_turn('不要留下半条记录', image_path=str(self.image), message_id='rollback')
        self.assertIsNone(self.core.store.get_message('rollback'))
        self.assertIsNone(self.core.attachments.path('rollback'))
        self.assertEqual('pending', self.core.store.get_scheduled_message(first['scheduled_message']).status)
        self.assertEqual(1, self.core.store.count_messages())

    def test_held_reply_recovers_without_new_model_call_after_restart(self):
        job = self.core.queue_user_turn('缓存回复')
        self.provider.action = lambda: composer_gate.note('default', True)
        self.core.execute_scheduled(job['scheduled_message'], force=True)
        self.core.close()
        self.core = CompanionCore(self.root / 'synthetic.db', provider=self.provider, learning_enabled=False)
        composer_gate.states.clear()
        self.provider.action = None
        self.assertTrue(self.core.execute_scheduled(job['scheduled_message'], force=True)['sent'])
        self.assertEqual(1, len(self.provider.contexts))

    def test_changed_character_does_not_reuse_old_held_reply(self):
        job = self.core.queue_user_turn('角色变了')
        self.provider.action = lambda: composer_gate.note('default', True)
        self.core.execute_scheduled(job['scheduled_message'], force=True)
        self.provider.action = None
        composer_gate.states.clear()
        self.core.context_builder.persona = build_persona({'name': 'NewName'})
        self.assertTrue(self.core.execute_scheduled(job['scheduled_message'], force=True)['sent'])
        self.assertEqual(2, len(self.provider.contexts))

    def test_held_reply_older_than_five_minutes_is_regenerated(self):
        job = self.core.queue_user_turn('时间过了')
        self.provider.action = lambda: composer_gate.note('default', True)
        self.core.execute_scheduled(job['scheduled_message'], force=True)
        key = 'turn_reply:' + job['scheduled_message']
        cached = json.loads(self.core.store.get_metadata(key))
        cached['generated_at'] = 0
        self.core.store.set_metadata(key, json.dumps(cached))
        composer_gate.states.clear()
        self.provider.action = None
        self.assertTrue(self.core.execute_scheduled(job['scheduled_message'], force=True)['sent'])
        self.assertEqual(2, len(self.provider.contexts))

    def test_deleting_one_bubble_invalidates_whole_turn_and_held_text(self):
        first = self.core.queue_user_turn('删除的内容')
        second = self.core.queue_user_turn('保留的内容')
        self.provider.action = lambda: composer_gate.note('default', True)
        self.core.execute_scheduled(second['scheduled_message'], force=True)
        self.core.delete_message(first['user_message_id'])
        self.assertIsNone(self.core.store.get_metadata('turn_reply:' + second['scheduled_message']))
        self.assertEqual([], self.core.store.list_scheduled_messages('pending'))
        self.assertEqual('failed', self.core.store.get_message(second['user_message_id']).status)

    def test_image_retries_preserve_every_attachment_in_the_turn(self):
        first = self.core.queue_user_turn('一', image_path=str(self.image))
        self.core.queue_user_turn('二', image_path=str(self.image))
        self.core.retry_message(first['user_message_id'])
        self.assertEqual(2, len(self.provider.contexts[-1]['current_images']))

    def test_bridge_has_dynamic_clock_and_clear_removes_image_files(self):
        config = {'provider': {}, 'attachment_root': str(self.root), 'learning': {'enabled': False}}
        try:
            android_bridge.initialize(str(self.root / 'bridge.db'), json.dumps(config))
            android_bridge.set_clock('2026-10-01T12:00:00+08:00', 'Asia/Shanghai')
            core = android_bridge._require_core()
            core.provider = self.provider
            core.supports_vision = True
            job = json.loads(android_bridge.queue_user_turn('图片', 'bridge-image', str(self.image)))
            result = json.loads(android_bridge.execute_scheduled(job['scheduled_message'], True))
            delivered = json.loads(android_bridge.get_message(result['message_id']))
            self.assertEqual(['bridge-image'], delivered['reply_source_ids'])
            self.assertIn('Asia/Shanghai', compile_dialogue_prompt(self.provider.contexts[-1]))
            android_bridge.clear_user_data()
            self.assertFalse(self.image.exists())
            self.assertEqual([], json.loads(android_bridge.list_messages()))
        finally:
            android_bridge.close()
