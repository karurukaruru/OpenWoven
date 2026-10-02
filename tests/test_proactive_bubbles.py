from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.core import CompanionCore
from adaptive_companion.delivery import DeliveryPlanner, DeliverySettings
from adaptive_companion.llm import OpenAICompatibleProvider, compile_dialogue_prompt
from adaptive_companion.proactive import ProactiveSettings
from tests.test_natural_character_and_topics import SyntheticCharacterProvider


def offline_core(path=':memory:', **kwargs):
    return CompanionCore(path, provider=SyntheticCharacterProvider(), learning_enabled=False,
                         proactive_settings=ProactiveSettings(quiet_start_hour=0, quiet_end_hour=0), **kwargs)


class ProactiveBubblePlannerTests(unittest.TestCase):
    def plan(self, text, **settings):
        return DeliveryPlanner(DeliverySettings(split_probability=0, **settings)).plan(
            text, 'fixed', {'context': 'technical', 'proactive': True})

    def test_chinese_opening_always_splits_and_uses_paced_gaps(self):
        plan = self.plan('想起你今天有考试。后来考得怎么样？有空再聊。')
        self.assertEqual(['想起你今天有考试', '后来考得怎么样？', '有空再聊'], [p.text for p in plan.parts])
        self.assertEqual('split', plan.mode)
        self.assertTrue(all(800 <= p.delay_ms <= 2500 for p in plan.parts[1:]))

    def test_long_essay_never_bypasses_splitting_or_glues_back_tail(self):
        plan = self.plan('今天还好吗？明天再说也行。' + '详细解释一下。' * 200 + '绝不拼回的尾巴。')
        self.assertEqual(3, len(plan.parts))
        self.assertTrue(all(len(p.text) <= 48 and '\n' not in p.text for p in plan.parts))
        self.assertNotIn('绝不拼回的尾巴', '\n'.join(p.text for p in plan.parts))

    def test_no_punctuation_or_single_long_line_is_still_bounded(self):
        for text in ('聊' * 1000, 'This is a very long unsolicited opening ' * 80):
            with self.subTest(text=text[:20]):
                plan = self.plan(text)
                self.assertTrue(plan.parts)
                self.assertLessEqual(len(plan.parts), 3)
                self.assertLessEqual(len(plan.parts[0].text), 48 if text.startswith('聊') else 120)
                self.assertTrue(plan.parts[0].text.endswith('…'))

    def test_long_comma_phrases_split_into_short_thoughts(self):
        phrases = ['这是一个挺长但仍然不超过一条短消息长度的话题' + str(i) for i in range(6)]
        plan = self.plan('，'.join(phrases))
        self.assertEqual(phrases[:3], [p.text for p in plan.parts])

    def test_markdown_numbering_and_repeated_punctuation_do_not_become_extra_messages(self):
        self.assertEqual(['最近怎么样？！', '有空再聊！！'],
                         [p.text for p in self.plan('1. 最近怎么样？！\n2. 有空再聊！！').parts])

    def test_four_languages_have_deterministic_separate_bubbles(self):
        cases = [('好呀。明天聊。', ['好呀', '明天聊']),
                 ('好呀。明天聊聊。', ['好呀', '明天聊聊']),
                 ('お疲れさま。試験はどうだった？また話そう。', ['お疲れさま', '試験はどうだった？', 'また話そう']),
                 ('Hey. How did it go? Talk later. More.', ['Hey.', 'How did it go?', 'Talk later.'])]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(expected, [p.text for p in self.plan(text).parts])

    def test_quotes_urls_numbers_and_times_do_not_break_into_fragments(self):
        text = '还记得“好呀。明天见。”吗？价格1,000和3.14，15:30再聊。看 https://example.invalid/a.b?q=1'
        self.assertEqual(['还记得“好呀。明天见。”吗？', '价格1,000和3.14，15:30再聊', '看 https://example.invalid/a.b?q=1'],
                         [p.text for p in self.plan(text).parts])

    def test_overlong_atomic_url_or_quote_is_omitted_not_corrupted(self):
        for atom in ('https://example.invalid/' + 'a' * 200, '“' + '聊' * 100 + '”'):
            self.assertEqual(['有空聊聊吗？'], [p.text for p in self.plan(atom + '\n有空聊聊吗？').parts])

    def test_disabled_timing_keeps_separate_messages_and_slow_model_only_removes_first_wait(self):
        self.assertEqual([0, 0], [p.delay_ms for p in self.plan('好呀。明天聊。', enabled=False).parts])
        plan = DeliveryPlanner().plan('好呀。明天聊。', 'fixed', {'proactive': True}, generation_latency_ms=30_000)
        self.assertEqual(0, plan.parts[0].delay_ms)
        self.assertGreaterEqual(plan.parts[1].delay_ms, 800)

    def test_document_or_topic_classification_cannot_override_proactive_shape(self):
        plan = DeliveryPlanner().plan('第一句。第二句。', policy={
            'proactive': True, 'context': 'serious_discussion', 'message_format': 'document'})
        self.assertEqual(['第一句', '第二句'], [p.text for p in plan.parts])


class ProactiveScheduledIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.core = offline_core()
        self.when = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()

    def tearDown(self):
        self.core.close()

    def topic_reply(self, response, topic='聊聊之前的书'):
        job = self.core.schedule_custom(topic, self.when, True)
        with patch.object(self.core.provider, 'generate', return_value=response) as generate:
            result = self.core.execute_scheduled(job['id'], force=True)
        self.assertEqual(1, generate.call_count)
        return job, result, generate.call_args.args[0]

    def test_topic_classified_as_advice_or_document_is_still_short_and_split(self):
        _, result, context = self.topic_reply('今天还好吗？那件事后来怎么样？有空再聊。多余的解释。', '建议：帮我写一份报告')
        self.assertTrue(context['interaction_policy']['proactive'])
        self.assertNotIn('message_format', context['interaction_policy'])
        self.assertLessEqual(context['interaction_policy']['reply_length'], .30)
        self.assertEqual(['今天还好吗？', '那件事后来怎么样？', '有空再聊'],
                         [p['text'] for p in result['delivery_plan']['parts']])
        self.assertNotIn('多余', result['text'])

    def test_database_notification_and_bridge_share_only_the_bounded_reply(self):
        _, result, _ = self.topic_reply('好呀。明天聊。慢慢来。多余解释。' * 80)
        self.assertEqual(result['text'], self.core.store.get_message(result['message_id']).content)
        self.assertEqual(result['text'], self.core.store.pending_notifications()[0]['text'])
        with patch.object(android_bridge, '_core', self.core):
            saved = json.loads(android_bridge.get_message(result['message_id']))
        self.assertEqual(result['delivery_plan'], saved['delivery_plan'])
        self.assertNotIn('多余解释', saved['content'])

    def test_short_visible_role_facts_survive_but_omitted_experiences_are_not_saved(self):
        raw = json.dumps({'reply': '我喜欢看书。最近看了什么？有空聊聊。我的高中是星河中学。', 'character_facts': [
            {'path': 'interests/books', 'value': '我喜欢看书'},
            {'path': 'education/high_school', 'value': '我的高中是星河中学'}]}, ensure_ascii=False)
        _, result, _ = self.topic_reply(raw)
        self.assertNotIn('星河中学', result['text'])
        self.assertEqual([{'path': 'interests/books', 'value': '我喜欢看书'}], self.core.character_book.entries())

    def test_overlong_atom_only_reply_gets_a_short_localized_opening_without_second_api_call(self):
        _, result, _ = self.topic_reply('“' + '聊' * 100 + '”')
        self.assertEqual('最近怎么样？', result['text'])
        self.assertEqual(1, len(result['delivery_plan']['parts']))

    def test_exact_scheduled_text_and_local_reminders_are_not_silently_shortened(self):
        exact = '明确要求保留的定时原文。' * 30
        with patch.object(self.core.provider, 'generate', side_effect=AssertionError('no model call')):
            job = self.core.schedule_custom(exact, self.when)
            result = self.core.execute_scheduled(job['id'], force=True)
        self.assertEqual(exact, result['text'])
        self.assertEqual([exact], [p['text'] for p in result['delivery_plan']['parts']])

    def test_automatic_checkin_uses_same_short_delivery_contract(self):
        now = datetime.now(UTC)
        for i in range(3):
            self.core.store.save_message('default', 'user', '聊聊书',
                timestamp=(now - timedelta(hours=3-i)).isoformat(), learning_status='disabled')
        job = self.core.proactive.plan_check_in('default', now)
        with patch.object(self.core.provider, 'generate', return_value='最近怎么样？上次那本书看完了吗？有空再聊。多余内容。'):
            result = self.core.execute_scheduled(job.id, force=True)
        self.assertTrue(result['sent'])
        self.assertEqual(3, len(result['delivery_plan']['parts']))
        self.assertNotIn('多余内容', result['text'])

    def test_restart_keeps_separate_messages_and_retry_never_regenerates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'synthetic.db'
            with offline_core(path) as core:
                job = core.schedule_custom('之前的书', self.when, True)
                with patch.object(core.provider, 'generate', return_value='最近怎么样？那本书看完了吗？'):
                    result = core.execute_scheduled(job['id'], force=True)
            with offline_core(path) as core, patch.object(core.provider, 'generate', side_effect=AssertionError('no repeat API')):
                self.assertEqual(result['delivery_plan'], core.store.delivery_plans_for([result['message_id']])[result['message_id']])
                self.assertEqual(result['text'], core.store.pending_notifications()[0]['text'])
                self.assertFalse(core.execute_scheduled(job['id'], force=True)['sent'])

    def test_proactive_prompt_and_output_budget_apply_even_to_noncasual_topics(self):
        _, _, context = self.topic_reply('那个代码后来跑通了吗？', '代码 API bug')
        prompt = compile_dialogue_prompt(context)
        self.assertIn('Proactive opening: 1–3 short messages', prompt)
        self.assertIn('not a request for an essay', prompt)
        self.assertIn('想起你今天有考试\n后来考得怎么样？', prompt)
        provider = OpenAICompatibleProvider('https://example.invalid', 'synthetic', 'synthetic-model', max_tokens=800)
        self.assertLessEqual(provider._output_budget(context), 256)
        plain = {**context, 'interaction_policy': {'reply_length': 1.0}}
        plain.pop('proactive_intent')
        self.assertEqual(800, provider._output_budget(plain))


if __name__ == '__main__':
    unittest.main()
