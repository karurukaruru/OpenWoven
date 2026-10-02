from __future__ import annotations

from copy import deepcopy
import unittest

from adaptive_companion.core import CompanionCore
from adaptive_companion.context import estimate_tokens
from adaptive_companion.character_interview import BASE_CHARACTER_INSTRUCTIONS
from adaptive_companion.llm import compile_dialogue_prompt
from adaptive_companion.persona import build_persona


class CharacterChatContractTests(unittest.TestCase):
    def context(self, persona=None):
        with CompanionCore(':memory:', persona=persona, learning_enabled=False) as core:
            return core.context_builder.build(core.aul(), core.current_policy('今天挺开心'),
                '今天挺开心', [], [], 5400)

    def test_runtime_starts_with_first_person_character_even_without_interview(self):
        prompt = compile_dialogue_prompt(self.context())
        self.assertTrue(prompt.startswith('Portray the selected fictional human character'))
        for instruction in ('Speak as I', 'without speaker labels', 'without unsolicited identity disclaimers'):
            self.assertIn(instruction, prompt)

    def test_direct_real_identity_is_truthful_not_a_human_impersonation_contract(self):
        prompt = compile_dialogue_prompt(self.context())
        self.assertIn('never present human identity or real offline experiences as factual', prompt)
        self.assertIn('Answer direct reality/identity questions truthfully', prompt)
        self.assertIn('never invent user facts', prompt)

    def test_same_role_contract_is_not_repeated_and_custom_data_is_not_mutated(self):
        persona = build_persona({'name': 'CharacterName', 'interview': {'q36': 'calm'}})
        persona['principles'].append('custom principle remains')
        context = self.context(persona)
        before = deepcopy(context['persona'])
        prompt = compile_dialogue_prompt(context)
        self.assertEqual(1, prompt.count(BASE_CHARACTER_INSTRUCTIONS))
        self.assertIn('CharacterName', prompt)
        self.assertIn('custom principle remains', prompt)
        self.assertEqual(before, context['persona'])

    def test_role_guidance_is_included_in_context_estimate(self):
        context = self.context(build_persona())
        self.assertEqual(context['estimated_tokens'],
            estimate_tokens(compile_dialogue_prompt(context)) + estimate_tokens(context['current_user_message']))
        self.assertLessEqual(context['estimated_tokens'], 5400)

    def test_absent_optional_principles_do_not_break_runtime_contract(self):
        context = self.context()
        context['persona']['principles'] = None
        prompt = compile_dialogue_prompt(context)
        self.assertEqual(1, prompt.count(BASE_CHARACTER_INSTRUCTIONS))
        self.assertIn('"principles":null', prompt)

    def test_background_continuity_and_language_keep_existing_guidance(self):
        context = self.context(build_persona({'name': 'Mio', 'language': 'ja'}))
        context['proactive_intent'] = 'ask how the exam went'
        prompt = compile_dialogue_prompt(context)
        self.assertIn('Default reply language: Japanese', prompt)
        self.assertIn('ask how the exam went', prompt)
        self.assertIn('names, ages, dates, places and relationships consistent', prompt)
