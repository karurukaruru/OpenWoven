from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.character_book import CharacterBook, parse_character_response
from adaptive_companion.context import estimate_tokens
from adaptive_companion.core import CompanionCore
from adaptive_companion.llm import LLMProvider, OpenAICompatibleProvider, compile_dialogue_prompt
from adaptive_companion.persona import build_persona
from adaptive_companion.proactive import ProactiveSettings
from adaptive_companion.turns import composer_gate

SCHOOL = 'education/high_school/school'
SCORE = 'education/high_school/entrance_score'

def envelope(reply, **facts):
    return json.dumps({'reply': reply, 'character_facts': [{'path': k, 'value': v} for k, v in facts.items()]}, ensure_ascii=False)

class BookProvider(LLMProvider):
    def __init__(self):
        self.output = envelope(['我高中读的是星河中学', '高考620分'], **{SCHOOL: '星河中学', SCORE: '620'})
        self.contexts = []
        self.action = None

    def generate(self, context):
        self.contexts.append(copy.deepcopy(context))
        if self.action:
            self.action()
        return self.output

def core_for(path=':memory:', provider=None, persona=None):
    return CompanionCore(path, provider=provider or BookProvider(), persona=persona or build_persona({'name': '小岚'}),
        learning_enabled=False, proactive_settings=ProactiveSettings(enabled=False, quiet_start_hour=0, quiet_end_hour=0))

class CharacterBookTests(unittest.TestCase):
    def setUp(self):
        composer_gate.states.clear()
        self.provider = BookProvider()
        self.core = core_for(provider=self.provider)

    def tearDown(self):
        self.core.close()
        composer_gate.states.clear()

    def test_delivered_reply_is_split_but_sidecar_never_reaches_chat(self):
        result = self.core.chat_result('你高中在哪里念书')
        self.assertEqual('我高中读的是星河中学\n高考620分', result['response'])
        self.assertEqual(['我高中读的是星河中学', '高考620分'], [x['text'] for x in result['delivery_plan']['parts']])
        saved = self.core.store.get_message(result['assistant_message_id'])
        self.assertNotIn('character_facts', saved.content)
        self.assertEqual({'school': {'value': '星河中学'}, 'entrance_score': {'value': '620'}},
            self.core.character_book.tree()['education']['high_school'])
        self.assertNotIn('星河中学', json.dumps(self.core.aul(), ensure_ascii=False))

    def test_book_survives_restart_without_injecting_unrelated_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'synthetic.db'
            with core_for(database) as core:
                core.chat('你高中在哪里念书')
                identity = core.character_book.character_id
            with core_for(database) as core:
                self.assertEqual(identity, core.character_book.character_id)
                self.assertEqual(2, len(core.character_book.retrieve('你高考考了多少分')))
                self.assertEqual([], core.character_book.retrieve('今天午饭吃啥'))
                with core.store.connection() as conn:
                    self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())

    def test_retrieved_character_chapter_has_budget_and_is_not_user_memory(self):
        self.core.chat('你高中在哪里念书')
        self.provider.output = envelope('620分')
        self.core.chat('你高考多少分')
        context = self.provider.contexts[-1]
        self.assertEqual(2, len(context['character_canon']))
        self.assertLessEqual(context['budget_allocation']['character'], 360)
        self.assertEqual(context['estimated_tokens'], estimate_tokens(compile_dialogue_prompt(context)) + estimate_tokens(context['current_user_message']))
        self.assertEqual(context['estimated_tokens'], sum(context['budget_allocation'].values()))
        self.assertLessEqual(context['estimated_tokens'], 5400)
        self.assertIn('authoritative data, not user facts', compile_dialogue_prompt(context))

    def test_conflicting_score_fails_without_overwriting_or_delivering(self):
        self.core.chat('你高中在哪里念书')
        self.provider.output = envelope('我高考650分', **{SCORE: '650'})
        with self.assertRaisesRegex(ValueError, 'canon conflict'):
            self.core.chat('高考多少分')
        self.assertEqual(1, self.core.store.count_messages(role='assistant'))
        self.assertEqual('failed', self.core.store.list_messages()[-1].status)
        self.assertEqual('620', self.core.character_book.tree()['education']['high_school']['entrance_score']['value'])

    def test_atomic_commit_rechecks_conflicts_and_rolls_back_reply_and_outbox(self):
        update = self.core.character_book.update([{'path': SCHOOL, 'value': '星河中学'}])
        self.core.chat('你高中在哪里念书')
        update['facts'][0]['value'] = '远山中学'
        job = self.core.queue_user_turn('还有呢')
        with self.assertRaisesRegex(ValueError, 'canon conflict'):
            self.core.store.complete_scheduled_delivery(job['scheduled_message'], '远山中学',
                reply_to_id=job['user_message_id'], character_update=update)
        self.assertEqual('pending', self.core.store.get_scheduled_message(job['scheduled_message']).status)
        self.assertEqual('waiting', self.core.store.get_message(job['user_message_id']).status)
        self.assertEqual(1, self.core.store.count_messages(role='assistant'))
        self.assertEqual([], self.core.store.pending_notifications())

    def test_held_reply_does_not_establish_canon_until_delivery(self):
        job = self.core.queue_user_turn('你高中在哪里念书')
        self.provider.action = lambda: composer_gate.note('default', True)
        self.assertFalse(self.core.execute_scheduled(job['scheduled_message'], force=True)['sent'])
        self.assertEqual([], self.core.character_book.entries())
        self.provider.action = None
        composer_gate.states.clear()
        result = self.core.execute_scheduled(job['scheduled_message'], force=True)
        self.assertTrue(result['sent'])
        self.assertEqual(1, len(self.provider.contexts))
        self.assertEqual(2, len(self.core.character_book.entries()))
        self.assertEqual(result['message_id'], self.core.store.pending_notifications()[0]['message_id'])

    def test_cancelled_held_reply_never_establishes_canon(self):
        job = self.core.queue_user_turn('你高中在哪里念书')
        self.provider.action = lambda: composer_gate.note('default', True)
        self.core.execute_scheduled(job['scheduled_message'], force=True)
        self.core.queue_user_turn('先不聊这个')
        self.assertIsNone(self.core.store.get_metadata('turn_reply:' + job['scheduled_message']))
        self.assertEqual([], self.core.character_book.entries())

    def test_retry_and_generated_schedule_also_use_book(self):
        source = self.core.store.save_message('default', 'user', '高中?', status='failed')
        result = self.core.retry_message(source.id)
        self.assertNotIn('character_facts', result['response'])
        self.assertEqual(2, len(self.core.character_book.entries()))
        self.provider.output = envelope('我大学读的是海城大学', **{'education/university/school': '海城大学'})
        when = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        job = self.core.schedule_custom('聊聊你的大学', when, generate=True)
        self.assertTrue(self.core.execute_scheduled(job['id'], force=True)['sent'])
        self.assertEqual('海城大学', self.core.character_book.tree()['education']['university']['school']['value'])

    def test_delete_source_removes_canon_and_clear_removes_all_books(self):
        result = self.core.chat_result('高中?')
        self.core.delete_message(result['user_message_id'])
        self.assertEqual([], self.core.character_book.entries())
        self.core.chat('高中?')
        self.core.store.clear_user_data()
        self.assertEqual([], self.core.character_book.entries())

    def test_nickname_and_language_preserve_book_but_new_foundation_is_separate(self):
        self.core.chat('高中?')
        renamed = CharacterBook(self.core.store, build_persona({'name': '岚岚', 'language': 'ja'}))
        self.assertEqual(self.core.character_book.character_id, renamed.character_id)
        self.assertEqual(2, len(renamed.entries()))
        different = CharacterBook(self.core.store, build_persona({'name': '岚岚', 'description': '另一位角色'}))
        self.assertNotEqual(renamed.character_id, different.character_id)
        self.assertEqual([], different.entries())

    def test_nickname_is_checked_but_not_archived_as_immutable(self):
        self.provider.output = envelope('我叫小岚', **{'identity/name': '小岚'})
        self.core.chat('叫什么')
        self.assertEqual([], self.core.character_book.entries())
        self.provider.output = envelope('我叫别人', **{'identity/name': '别人'})
        with self.assertRaisesRegex(ValueError, 'configured name'):
            self.core.chat('叫什么')

    def test_same_day_location_cannot_be_silently_changed(self):
        path = 'experiences/travel/2024_06_03/location'
        self.provider.output = envelope('2024年6月3日这天我在热海', **{path: '热海'})
        self.core.chat('聊聊旅行')
        self.provider.output = envelope('那天我在昆明', **{path: '昆明'})
        with self.assertRaisesRegex(ValueError, 'canon conflict'):
            self.core.chat('那天在哪里')

    def test_date_question_retrieves_the_exact_day_without_a_travel_keyword(self):
        self.provider.output = envelope('6月3日我在热海，6月4日我在昆明', **{
            'experiences/travel/2024_06_03/location': '热海',
            'experiences/travel/2024_06_04/location': '昆明'})
        self.core.chat('聊聊旅行')
        for query in ('你2024年6月3日在哪里', 'Where were you on 2024-06-03?', '2024/6/3'):
            with self.subTest(query=query):
                found = self.core.character_book.retrieve(query)
                self.assertEqual([{'path': 'experiences/travel/2024_06_03/location', 'value': '热海'}], found)
        self.assertEqual([], self.core.character_book.retrieve('2024-02-30'))

    def test_bridge_exports_hierarchy_separately(self):
        self.core.chat('高中?')
        with patch.object(android_bridge, '_core', self.core):
            exported = json.loads(android_bridge.get_character_book())
        self.assertIn('high_school', exported['chapters']['education'])
        self.assertNotIn('character_facts', exported)

    def test_plain_reply_is_compatible_for_both_extension_and_configured_provider(self):
        self.provider.output = '今天吃寿司吧'
        self.assertEqual('今天吃寿司吧', self.core.chat('吃什么'))
        actual = OpenAICompatibleProvider('https://example.invalid/v1', 'synthetic-not-a-key', 'fixture')
        with core_for(provider=actual) as core, patch.object(actual, '_send', return_value={'choices': [{'message': {'content': '好呀，今天吃寿司吧'}}]}):
            self.assertEqual('好呀，今天吃寿司吧', core.chat('你好'))
            self.assertEqual(1, core.store.count_messages(role='assistant'))
            self.assertEqual([], core.character_book.entries())

    def test_real_provider_roundtrip_and_output_cap_with_no_network(self):
        actual = OpenAICompatibleProvider('https://example.invalid/v1', 'synthetic-not-a-key', 'fixture')
        payload = {'choices': [{'message': {'content': self.provider.output}}], 'usage': {'prompt_tokens': 300, 'completion_tokens': 80}}
        with core_for(provider=actual) as core, patch.object(actual, '_send', return_value=payload) as send:
            result = core.chat_result('高中?')
            request = json.loads(send.call_args.args[0].data)
            self.assertIn('Reply normally in plain text', request['messages'][0]['content'])
            self.assertLessEqual(request['max_tokens'], 800)
            self.assertEqual(2, len(core.character_book.entries()))
            self.assertNotIn('character_facts', result['response'])

    def test_failed_validation_still_records_reported_billable_usage(self):
        actual = OpenAICompatibleProvider('https://example.invalid/v1', 'synthetic-not-a-key', 'fixture')
        payload = {'choices': [{'message': {'content': '{"reply":"incomplete'}}],
                   'usage': {'prompt_tokens': 321, 'completion_tokens': 123}}
        with core_for(provider=actual) as core, patch.object(actual, '_send', return_value=payload):
            with self.assertRaises(ValueError):
                core.chat('高中?')
            metrics = core.store.list_generation_metrics()
            self.assertEqual(1, len(metrics))
            self.assertEqual('failed', metrics[0]['status'])
            self.assertEqual(321, metrics[0]['prompt_tokens'])
            self.assertEqual(123, metrics[0]['completion_tokens'])
            self.assertEqual(0, core.store.count_messages(role='assistant'))

    def test_small_budget_never_includes_an_oversized_book_chapter(self):
        entries = [{'path': 'experiences/event_' + str(i) + '/detail', 'value': '角色经历' * 35} for i in range(18)]
        context = self.core.context_builder.build(self.core.aul(), self.core.current_policy('高中?'),
            '高中?', [], [], 1600, character_entries=entries, character_book_enabled=True)
        self.assertLessEqual(context['budget_allocation']['character'], 360)
        self.assertLessEqual(context['estimated_tokens'], 1600)
        self.assertLess(len(context['character_canon']), len(entries))
        self.assertEqual(context['estimated_tokens'], estimate_tokens(compile_dialogue_prompt(context)) + estimate_tokens('高中?'))

class CharacterEnvelopeTests(unittest.TestCase):
    def test_bad_schema_values_or_unspoken_facts_are_never_displayed(self):
        invalid = [
            '{"reply":"hi","character_facts":',
            envelope('你好', **{SCHOOL: '虚构中学'}),
            envelope('你好', **{'user/school': '你好'}),
            '{"reply":[""],"character_facts":[]}',
            '{"reply":"hi","character_facts":null}',
            '{"reply":"hi","character_facts":[],"debug":"internal"}',
            envelope('热海', **{'experiences/travel/2024_02_30/location': '热海'}),
            envelope('热海', **{'experiences/travel/2024_2_3/location': '热海'}),
            envelope('热海', **{'experiences/travel/2024_02_30/hotel/name': '热海'}),
            envelope('高中', **{'education/high_school/value': '高中'}),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_character_response(value)

    def test_markdown_envelope_is_stripped_and_duplicate_slots_are_checked(self):
        reply, facts = parse_character_response('```json\n' + envelope(['星河中学', '620分'], **{SCHOOL: '星河中学'}) + '\n```')
        self.assertEqual('星河中学\n620分', reply)
        raw = json.dumps({'reply': '620还是650', 'character_facts': [{'path': SCORE, 'value': '620'}, {'path': SCORE, 'value': '650'}]})
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            parse_character_response(raw)

    def test_parent_and_child_paths_cannot_corrupt_tree(self):
        with core_for() as core:
            core.provider.output = envelope('学校生活\n星河中学', **{'education/high_school': '学校生活', SCHOOL: '星河中学'})
            core.chat('高中?')
            chapter = core.character_book.tree()['education']['high_school']
            self.assertEqual('学校生活', chapter['value'])
            self.assertEqual('星河中学', chapter['school']['value'])

    def test_migration_from_v10_keeps_history_and_existing_notifications(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'synthetic.db'
            with core_for(database) as core:
                job = core.queue_user_turn('高中?')
                result = core.execute_scheduled(job['scheduled_message'], force=True)
                with core.store.connection() as conn:
                    conn.execute('DROP TABLE character_facts')
                    conn.execute('PRAGMA user_version=10')
                    conn.commit()
            with core_for(database) as upgraded:
                self.assertEqual(result['text'], upgraded.store.get_message(result['message_id']).content)
                self.assertEqual(1, len(upgraded.store.pending_notifications()))
                self.assertEqual([], upgraded.character_book.entries())
                with upgraded.store.connection() as conn:
                    self.assertEqual(11, conn.execute('PRAGMA user_version').fetchone()[0])
                    self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())
