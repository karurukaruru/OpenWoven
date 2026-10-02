from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.core import CompanionCore
from adaptive_companion.context import estimate_tokens
from adaptive_companion.llm import LLMProvider, compile_dialogue_prompt
from adaptive_companion.localization import LANGUAGES, STRINGS
from adaptive_companion.models import DEFAULT_PERSONA, Evidence
from adaptive_companion.persona import CHOICES, PRESETS, build_persona


class CapturingProvider(LLMProvider):
    def generate(self, context):
        self.context = context
        return 'synthetic response'


class PersonaTests(unittest.TestCase):
    def test_invalid_configuration_uses_safe_defaults(self):
        for config in (None, [], {'preset': [], 'language': {}}, {'preset': 'unknown', 'choices': []}):
            with self.subTest(config=config):
                persona = build_persona(config)
                self.assertEqual('companion', persona['preset'])
                self.assertEqual('Simplified Chinese', persona['language'])

    def test_presets_and_choices_are_bounded_and_independent(self):
        original = json.dumps(DEFAULT_PERSONA)
        for preset in PRESETS:
            for scenario, choices in CHOICES.items():
                for choice in choices:
                    with self.subTest(preset=preset, choice=choice):
                        persona = build_persona({'preset': preset, 'choices': {scenario: choice}})
                        self.assertEqual(choice, persona['scenario_choices'][scenario])
                        self.assertTrue(all(0 <= x <= 1 for x in persona['initial_style'].values()))
        self.assertEqual(original, json.dumps(DEFAULT_PERSONA))

    def test_custom_fields_are_trimmed_and_limited(self):
        persona = build_persona({'name': 'x'*100, 'description': 'z'*2000, 'boundaries': 'b'*2000,
                                'choices': {'support': 'listen', 'bad': 'bad', 'detail': []}})
        self.assertEqual((40, 600, 300), tuple(len(persona[k]) for k in ('name', 'description', 'boundaries')))
        self.assertEqual({'support': 'listen'}, persona['scenario_choices'])

    def test_role_is_in_first_prompt_not_user_facts(self):
        provider = CapturingProvider()
        persona = build_persona({'preset': 'custom', 'name': 'RoleOnlyName', 'description': 'Quiet fictional librarian',
                                 'boundaries': 'No nicknames', 'language': 'ja'})
        with CompanionCore(':memory:', persona=persona, provider=provider, learning_enabled=False) as core:
            core.chat('hello')
            prompt = compile_dialogue_prompt(provider.context)
            for item in ('RoleOnlyName', 'Quiet fictional librarian', 'No nicknames', 'Japanese', 'Character backstory is fictional'):
                self.assertIn(item, prompt)
            self.assertIn('explicitly requests', prompt)
            self.assertNotIn('RoleOnlyName', json.dumps(core.aul()['profile']))
            self.assertNotIn('initial_style', prompt)
            self.assertEqual([], core.store.list_evidence())

    def test_initial_style_is_not_fabricated_user_evidence(self):
        with CompanionCore(':memory:', persona=build_persona({'preset': 'listener'}), learning_enabled=False) as core:
            pref = core.aul()['interaction']['advice_frequency']
            self.assertEqual(.2, pref['value'])
            self.assertEqual(0, pref['evidence_count'])
            self.assertEqual(0, pref['confidence'])
            self.assertEqual([], core.store.list_evidence())

    def test_first_feedback_refines_selected_seed_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'role.db'
            persona = build_persona({'preset': 'listener'})
            with CompanionCore(db, persona=persona, learning_enabled=False) as core:
                result = core.chat_result('test')
                core.submit_feedback(result['assistant_message_id'], 'too_many_questions')
                value = core.aul()['interaction']['question_frequency']['value']
                self.assertLess(value, .25)
            with CompanionCore(db, persona=persona, learning_enabled=False) as core:
                self.assertEqual(value, core.aul()['interaction']['question_frequency']['value'])

    def test_weak_signal_does_not_jump_back_to_generic_half(self):
        with CompanionCore(':memory:', persona=build_persona({'preset': 'listener'}), learning_enabled=False) as core:
            message = core.store.save_message('default', 'user', 'synthetic weak signal')
            core.store.save_evidence([Evidence('seed-test', 'interaction_preference', 'interaction.advice_frequency',
                direction='increase', strength=.5, confidence=.5, source_message_id=message.id, signal='implicit')])
            value = core.learning.aggregator.aggregate()['interaction']['advice_frequency']['value']
            self.assertGreater(value, .2)
            self.assertLess(value, .23)

    def test_role_switch_preserves_learned_preference_but_updates_unlearned_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'switch.db'
            with CompanionCore(db, persona=build_persona({'preset': 'listener'}), learning_enabled=False) as core:
                core.set_preference_baseline('question_frequency', .1)
                previous = core.aul()['interaction']['question_frequency']
            with CompanionCore(db, persona=build_persona({'preset': 'playful'}), learning_enabled=False) as core:
                self.assertEqual(previous, core.aul()['interaction']['question_frequency'])
                self.assertEqual(.75, core.aul()['interaction']['humor']['value'])
                self.assertLess(core.current_policy('hello')['question_frequency'], .2)

    def test_explicit_current_emotion_overrides_playful_tone_in_four_languages(self):
        with CompanionCore(':memory:', persona=build_persona({'preset': 'playful'}), learning_enabled=False) as core:
            for text in ('我很难过', '我很難過', '悲しい', 'I feel sad'):
                policy = core.current_policy(text)
                self.assertEqual('emotional', policy['context'])
                self.assertLess(policy['humor'], .75)

    def test_local_runtime_has_four_languages_for_every_message(self):
        for values in STRINGS.values():
            self.assertEqual(len(LANGUAGES), len(values))
            self.assertTrue(all(values))

    def test_japanese_kana_is_not_estimated_as_cheap_latin_text(self):
        self.assertEqual(8, estimate_tokens('こんにちはカタカ'))
        self.assertEqual(2, estimate_tokens('abcdefgh'))

    def test_unlearned_role_changes_are_audited_as_configuration_not_evidence(self):
        with CompanionCore(':memory:', persona=build_persona({'preset': 'listener'}), learning_enabled=False) as core:
            audit = core.store.list_audit('interaction.advice_frequency')
            self.assertIn('configured starting style', audit[0]['reason'])
            self.assertIsNone(audit[0]['evidence_id'])
            self.assertEqual(0, audit[0]['confidence'])

    def test_offline_reply_language(self):
        for code, expected in [('zh-CN', '我记下了'), ('zh-TW', '我記下了'), ('ja', '覚えておきます'), ('en-US', "I'll keep that in mind")]:
            with self.subTest(code=code), CompanionCore(':memory:', persona=build_persona({'language': code}), learning_enabled=False) as core:
                self.assertIn(expected, core.chat('hello'))

    def test_local_exam_clarification_language(self):
        for code, expected in [('zh-TW', '幾點結束'), ('ja', '何時に終わります'), ('en-US', 'at what time')]:
            with self.subTest(code=code), CompanionCore(':memory:', persona=build_persona({'language': code}), learning_enabled=False) as core:
                self.assertIn(expected, core.chat('我过段时间有高数考试'))

    def test_bridge_initialization_and_role_do_not_call_network(self):
        try:
            with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
                config = {'persona': {'preset': 'listener', 'language': 'en-US'}, 'provider': {}, 'learning': {'enabled': False}}
                android_bridge.initialize(str(Path(tmp) / 'bridge.db'), json.dumps(config))
                result = json.loads(android_bridge.send_message('hello'))
                self.assertIn("I'll keep that in mind", result['response'])
                self.assertEqual(0.2, json.loads(android_bridge.get_aul())['interaction']['advice_frequency']['value'])
                android_bridge.clear_user_data()
                self.assertEqual(0.2, json.loads(android_bridge.get_aul())['interaction']['advice_frequency']['value'])
                self.assertFalse(json.loads(android_bridge.test_connection('{}'))['ok'])
                android_bridge.close()
        finally:
            android_bridge.close()


if __name__ == '__main__':
    unittest.main()
