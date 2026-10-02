from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from adaptive_companion.character_book import BOOK_INSTRUCTIONS, CharacterMetadataError, parse_character_response
from adaptive_companion.context import estimate_tokens
from adaptive_companion.llm import OpenAICompatibleProvider, compile_dialogue_prompt
from adaptive_companion.persona import RUNTIME_REDUNDANT_PRINCIPLES, build_persona
from tests.test_character_book import core_for, envelope


class LightweightCharacterMemoryTests(unittest.TestCase):
    def test_no_required_categories_or_plain_reply_json_wrapper(self):
        self.assertIn('Reply normally in plain text', BOOK_INSTRUCTIONS)
        self.assertIn('optionally return', BOOK_INSTRUCTIONS)
        self.assertIn('need no fixed categories', BOOK_INSTRUCTIONS)
        self.assertNotIn('Return JSON only', BOOK_INSTRUCTIONS)
        self.assertNotIn('entrance_score', BOOK_INSTRUCTIONS)

    def test_free_descriptive_record_keys_are_persisted_and_retrievable(self):
        with core_for() as core:
            core.provider.output = envelope('我最喜欢乌龙茶', **{'facts/喜欢的饮品': '乌龙茶'})
            core.chat('你喜欢喝什么')
            entries = core.character_book.retrieve('喜欢的饮品是什么')
            self.assertEqual([{'path': 'facts/喜欢的饮品', 'value': '乌龙茶'}], entries)
            self.assertEqual('乌龙茶', core.character_book.tree()['facts']['喜欢的饮品']['value'])

    def test_legacy_categories_and_english_free_keys_remain_searchable(self):
        with core_for() as core:
            core.provider.output = envelope('我在星河中学读高中', **{'facts/high_school': '星河中学'})
            core.chat('你的高中在哪')
            self.assertEqual('星河中学', core.character_book.retrieve('高中在哪里')[0]['value'])

    def test_bad_optional_archive_does_not_spoil_a_valid_chat_reply(self):
        with core_for() as core:
            core.provider.output = envelope('今天吃寿司吧', **{'user/private_fact': '没有说过的东西'})
            result = core.chat_result('吃什么')
            self.assertEqual('今天吃寿司吧', result['response'])
            self.assertEqual([], core.character_book.entries())
            metric = core.store.list_generation_metrics()[0]
            self.assertEqual('success', metric['status'])
            self.assertIn('Character archive skipped', metric['error'])
            self.assertNotIn('character_facts', core.store.get_message(result['assistant_message_id']).content)

    def test_two_conflicting_claims_in_the_same_reply_are_not_softened_as_metadata_errors(self):
        with core_for() as core:
            core.provider.output = json.dumps({'reply': '我高考620分，也考了650分', 'character_facts': [
                {'path': 'facts/高考成绩', 'value': '620'}, {'path': 'facts/高考成绩', 'value': '650'}]})
            with self.assertRaisesRegex(ValueError, 'Conflicting character facts'):
                core.chat('你考多少分')
            self.assertEqual(0, core.store.count_messages(role='assistant'))

    def test_plain_reply_does_not_validate_the_whole_book_and_full_book_does_not_block_chat(self):
        with core_for() as core:
            core.provider.output = '今天吃寿司吧'
            with patch.object(core.character_book, 'validate', side_effect=AssertionError('unnecessary read')):
                self.assertEqual('今天吃寿司吧', core.chat('吃什么'))
            core.provider.output = envelope('我喜欢乌龙茶', **{'facts/喜欢饮品': '乌龙茶'})
            with patch('adaptive_companion.character_book.MAX_FACTS', 0):
                self.assertEqual('我喜欢乌龙茶', core.chat('喝什么'))
                self.assertEqual([], core.character_book.entries())
            self.assertIn('book is full', core.store.list_generation_metrics()[0]['error'])

    def test_strict_metadata_validation_still_reports_invalid_facts(self):
        with self.assertRaises(CharacterMetadataError) as caught:
            parse_character_response(envelope('你好', **{'facts/学校': '正文没出现的学校'}))
        self.assertEqual('你好', caught.exception.reply)

    def test_requested_json_is_not_mistaken_for_private_metadata(self):
        raw = '{"reply":"requested data","status":"ok"}'
        self.assertEqual((raw, []), parse_character_response(raw))
        with core_for() as core:
            core.provider.output = raw
            self.assertEqual(raw, core.chat('请返回JSON数据'))

    def test_technical_and_creative_documents_do_not_use_archive_protocol(self):
        with core_for() as core:
            for query, reply in [('帮我检查代码', '{"character_facts":[],"reply":"example data"}'),
                                 ('帮我写一个故事', '那是一个雨天，另一个女孩走进了学校。')]:
                with self.subTest(query=query):
                    core.provider.output = reply
                    self.assertEqual(reply, core.chat(query))
                    context = core.provider.contexts[-1]
                    self.assertNotIn('character_book_enabled', context)
                    self.assertNotIn(BOOK_INSTRUCTIONS, compile_dialogue_prompt(context))
            self.assertEqual([], core.character_book.entries())

    def test_chat_output_limit_is_not_increased_by_archiving(self):
        provider = OpenAICompatibleProvider('https://example.invalid/v1', 'synthetic-not-a-key', 'fixture', max_tokens=800)
        base = {'interaction_policy': {'reply_length': .3}}
        with_archive = {**base, 'character_book_enabled': True}
        self.assertEqual(provider._output_budget(base), provider._output_budget(with_archive))
        self.assertLess(provider._output_budget(with_archive), 500)

    def test_redundant_role_rules_are_projected_out_without_mutating_custom_persona(self):
        with core_for(persona=build_persona({'name': '小岚'})) as core:
            core.context_builder.persona['principles'].append('Custom requirement: enjoy chess')
            context = core.context_builder.build(core.aul(), core.current_policy('你好'), '你好', [], [], 5400)
            before = copy.deepcopy(context['persona'])
            prompt = compile_dialogue_prompt(context)
            self.assertIn('Custom requirement: enjoy chess', prompt)
            self.assertIn('without blind flattery', prompt)
            self.assertIn('Answer direct reality/identity questions truthfully', prompt)
            serialized = prompt.split('Persona: ', 1)[1].split('\n\n', 1)[0]
            principles = json.loads(serialized)['principles']
            self.assertTrue(RUNTIME_REDUNDANT_PRINCIPLES.isdisjoint(principles))
            self.assertEqual(before, context['persona'])

    def test_exact_recent_quotation_is_not_sent_again_as_old_memory(self):
        with core_for() as core:
            text = '我喜欢春天的天气'
            recent = [core.store.save_message('default', 'user', text)]
            query = '继续聊聊'
            context = core.context_builder.build(core.aul(), core.current_policy(query), query, recent,
                [{'kind': 'long_term', 'text': '我 喜欢 春天的天气'}], 2000)
            self.assertEqual([], context['relevant_memories'])
            self.assertEqual(0, context['budget_allocation']['memory'])
            self.assertEqual(1, len(context['recent_conversation']))
            self.assertFalse(any('Historical quotations' in x for x in context['policy_instructions']))
            self.assertEqual(context['estimated_tokens'], sum(context['budget_allocation'].values()))
            self.assertEqual(context['estimated_tokens'], estimate_tokens(compile_dialogue_prompt(context)) + estimate_tokens(query))

    def test_memory_copy_is_kept_when_original_turn_does_not_fit_recent_budget(self):
        with core_for() as core:
            text = '旧经历' * 2500
            recent = [core.store.save_message('default', 'user', text)]
            context = core.context_builder.build(core.aul(), core.current_policy('之前的事'), '之前的事', recent,
                [{'kind': 'long_term', 'text': text}], 2000)
            self.assertEqual([], context['recent_conversation'])
            self.assertTrue(context['relevant_memories'])
            self.assertLessEqual(context['estimated_tokens'], 2000)

    def test_short_dialogue_prompt_has_bounded_overhead(self):
        with core_for(persona=build_persona({'name': '小岚', 'description': '平等相处，喜欢轻松日常聊天'})) as core:
            core.context_builder.clock = lambda: '2026-10-01T13:00:00+08:00'
            query = '今天吃什么'
            context = core.context_builder.build(core.aul(), core.current_policy(query), query, [], [], 5400,
                character_book_enabled=True)
            # The pre-change identical synthetic fixture was 963 estimated
            # tokens. This guards overhead, not provider pricing or quality.
            self.assertLess(context['estimated_tokens'], 750)
            self.assertLessEqual(estimate_tokens(BOOK_INSTRUCTIONS), 160)
