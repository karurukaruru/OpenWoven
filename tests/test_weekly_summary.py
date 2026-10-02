"""Model summary requests are tested with synthetic providers, never live keys."""
import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from adaptive_companion.core import CompanionCore
from adaptive_companion.context import estimate_tokens
from adaptive_companion.llm import LLMProvider, OpenAICompatibleProvider
from adaptive_companion.models import Evidence


class SummaryProvider(LLMProvider):
    def __init__(self):
        self.prompts = []
        self.action = None

    def generate(self, context):
        raise AssertionError('A memory summary must not use the chat/roleplay path')

    def generate_memory_summary(self, prompt):
        self.prompts.append(prompt)
        if self.action:
            self.action()
        return '这一周讨论了旅行计划，并决定周末去苏州。'


class WeeklySummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'synthetic.db'
        self.provider = SummaryProvider()
        self.core = CompanionCore(self.path, provider=self.provider, learning_enabled=False)
        self.core.wait_for_learning()
        self.addCleanup(self.core.close)
        self.message = self.core.store.save_message('archive', 'user', '周末去苏州旅行',
            timestamp='2026-01-06T12:00:00+08:00', learning_status='disabled')

    def maintain(self):
        return self.core.memory.maintain(datetime.fromisoformat('2026-02-02T12:00:00+08:00'))

    def test_actual_model_summary_stored_once_with_sources_and_metrics(self):
        self.maintain()
        archive = self.core.memory.archives.list('weekly')[0]
        self.assertEqual('llm', archive['content']['summary_method'])
        self.assertIn('苏州', archive['content']['summary'])
        self.assertEqual(self.message.id, self.core.memory.archives.detail(archive['memory_id'])['messages'][0]['id'])
        self.maintain()
        self.core.memory.consolidate_weekly('2026-01-11')
        self.assertEqual(1, len(self.provider.prompts))
        self.assertEqual('memory_summary', self.core.store.list_generation_metrics()[0]['kind'])

    def test_network_failure_keeps_dirty_work_and_originals_and_throttles(self):
        def fail():
            raise OSError('synthetic failure')
        self.provider.action = fail
        self.maintain()
        self.maintain()
        self.assertEqual(1, len(self.provider.prompts))
        self.assertEqual([], self.core.memory.archives.list('weekly'))
        self.assertIsNotNone(self.core.store.get_message(self.message.id))
        self.assertEqual('failed', self.core.store.list_generation_metrics()[0]['status'])
        # The same retry state survives a restart/configuration change.
        self.core.close()
        self.core = CompanionCore(self.path, provider=self.provider, learning_enabled=False)
        self.addCleanup(self.core.close)
        self.core.wait_for_learning()
        self.assertEqual(1, len(self.provider.prompts))
        self.core.store.set_metadata('weekly_summary_retry:2026-01-05..2026-01-11', '')
        self.provider.action = None
        self.maintain()
        self.assertEqual('llm', self.core.memory.archives.list('weekly')[0]['content']['summary_method'])

    def test_deletion_during_network_cannot_resurrect_memory(self):
        self.provider.action = lambda: self.core.delete_message(self.message.id)
        self.maintain()
        self.assertEqual([], self.core.memory.archives.list('weekly'))
        self.assertIsNone(self.core.store.get_message(self.message.id))

    def test_late_evidence_invalidates_inflight_snapshot(self):
        self.provider.action = lambda: self.core.store.save_evidence([Evidence(
            id='late', type='event', key='current.recent_events', value='旅行取消', source_message_id=self.message.id)])
        self.maintain()
        self.assertEqual([], self.core.memory.archives.list('weekly'))

    def test_model_request_does_not_hold_the_database_lock(self):
        def check_lock():
            finished = threading.Event()
            def read():
                self.core.store.count_messages()
                finished.set()
            worker = threading.Thread(target=read)
            worker.start()
            self.assertTrue(finished.wait(2), 'model call held the store lock')
            worker.join()
        self.provider.action = check_lock
        self.maintain()
        self.assertEqual(1, len(self.core.memory.archives.list('weekly')))

    def test_long_week_has_a_bounded_prompt(self):
        for i in range(40):
            self.core.store.save_message('archive', 'user', '长内容' * 3000,
                timestamp=f'2026-01-{5 + i % 7:02}T12:00:00+08:00', learning_status='disabled')
        self.maintain()
        self.assertLessEqual(estimate_tokens(self.provider.prompts[0]), 5000)
        data = json.loads(self.provider.prompts[0])
        self.assertEqual(7, len(data['records']))
        self.assertTrue(all(r['excerpts'] for r in data['records']))

    def test_local_archive_is_upgraded_when_model_becomes_available(self):
        self.core.memory.archives.weekly_summarizer = None
        self.maintain()
        self.core.memory.archives.weekly_summarizer = self.core.memory.weekly_summarizer
        self.maintain()
        self.assertEqual('llm', self.core.memory.archives.list('weekly')[0]['content']['summary_method'])

    def test_empty_or_oversized_responses_are_not_sealed(self):
        with patch.object(SummaryProvider, 'generate_memory_summary', return_value=' '):
            self.maintain()
        self.assertEqual([], self.core.memory.archives.list('weekly'))
        self.core.store.set_metadata('weekly_summary_retry:2026-01-05..2026-01-11', '')
        with patch.object(SummaryProvider, 'generate_memory_summary', return_value='x' * 6001):
            self.maintain()
        self.assertEqual([], self.core.memory.archives.list('weekly'))

    def test_summary_is_searchable_as_historical_memory(self):
        self.maintain()
        found = self.core.retriever.retrieve('苏州 旅行')
        self.assertTrue(any(item['kind'] == 'weekly' and '苏州' in item['text'] for item in found))

    def test_only_one_week_is_generated_per_maintenance(self):
        self.core.store.save_message('archive', 'user', '第二周的旅行',
            timestamp='2026-01-13T12:00:00+08:00', learning_status='disabled')
        self.maintain()
        self.assertEqual(1, len(self.provider.prompts))
        self.maintain()
        self.assertEqual(2, len(self.provider.prompts))

    def test_archive_screen_displays_generated_summary(self):
        screen = Path(__file__).resolve().parents[1] / 'android/app/src/main/java/com/adaptive/companion/ui/ArchiveBrowserScreen.kt'
        self.assertGreaterEqual(screen.read_text(encoding='utf-8').count('optString("summary")'), 2)


class SummaryHTTPTests(unittest.TestCase):
    def test_dedicated_request_does_not_contain_character_prompt(self):
        provider = OpenAICompatibleProvider('https://example.invalid/v1', 'synthetic-key', 'synthetic-model')
        payload = {'choices': [{'message': {'content': 'Summary'}, 'finish_reason': 'stop'}],
                   'usage': {'prompt_tokens': 123, 'completion_tokens': 12}}
        with patch.object(OpenAICompatibleProvider, '_send', return_value=payload) as send:
            self.assertEqual('Summary', provider.generate_memory_summary('synthetic records'))
        request = json.loads(send.call_args.args[0].data)
        self.assertIn('not a roleplay', request['messages'][0]['content'])
        self.assertEqual(0.2, request['temperature'])
        self.assertLessEqual(request['max_tokens'], 800)
        self.assertEqual(12, provider.request_usage['completion_tokens'])

    def test_truncated_summary_is_rejected_but_usage_is_retained(self):
        provider = OpenAICompatibleProvider('https://example.invalid/v1', 'synthetic-key', 'synthetic-model')
        payload = {'choices': [{'message': {'content': 'partial'}, 'finish_reason': 'length'}],
                   'usage': {'prompt_tokens': 123, 'completion_tokens': 800}}
        with patch.object(OpenAICompatibleProvider, '_send', return_value=payload):
            with self.assertRaises(ValueError):
                provider.generate_memory_summary('synthetic records')
        self.assertEqual(800, provider.request_usage['completion_tokens'])


if __name__ == '__main__':
    unittest.main()
