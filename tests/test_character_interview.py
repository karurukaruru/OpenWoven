from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.character_interview import (
    CHARACTER_IDS, STYLE_IDS, character_generation_prompt, clean_answers,
    has_first_ten, interview_persona, nickname_candidates,
)
from adaptive_companion.core import CompanionCore
from adaptive_companion.llm import LLMProvider, compile_dialogue_prompt
from adaptive_companion.onboarding import QUESTIONS, RECOMMENDED_IDS, UNSURE
from adaptive_companion.persona import build_persona


def answers():
    return dict(zip(RECOMMENDED_IDS, [
        'UserOnlyName', 'student', 'piano', 'learn calculus', 'no patronizing',
        'calm with independent views', 'female', 'equal friends', 'listen', 'no guilt',
    ]))


class Capture(LLMProvider):
    def generate(self, context):
        self.context = context
        return 'offline test reply'


class CharacterInterviewTests(unittest.TestCase):
    def test_question_order_is_five_plus_five_then_twenty_plus_twenty(self):
        self.assertEqual(50, len(QUESTIONS))
        self.assertEqual(50, len({q.id for q in QUESTIONS}))
        self.assertEqual(list(RECOMMENDED_IDS), [q.id for q in QUESTIONS[:10]])
        targets = [q.public()['target'] for q in QUESTIONS]
        self.assertEqual(['user'] * 5 + ['persona'] * 5 + ['user'] * 20 + ['persona'] * 20, targets)

    def test_legacy_ids_keep_their_meaning(self):
        by_id = {q.id: q for q in QUESTIONS}
        self.assertEqual('profile.name', by_id['q01'].key)
        self.assertEqual('profile.job', by_id['q06'].key)
        self.assertEqual('interaction.advice_frequency', by_id['q29'].key)
        self.assertEqual('interaction.emoji_frequency', by_id['q30'].key)

    def test_first_ten_required_for_character_generation(self):
        for missing in RECOMMENDED_IDS:
            value = answers()
            value[missing] = '  '
            self.assertFalse(has_first_ten(value))
            with self.assertRaises(ValueError):
                interview_persona(value)
        self.assertTrue(has_first_ten(answers()))

    def test_unknown_is_valid_response_but_never_a_fact(self):
        unknown = {key: UNSURE for key in RECOMMENDED_IDS}
        draft = interview_persona(unknown)
        self.assertEqual({}, draft['interview'])
        self.assertEqual('', draft['boundaries'])
        with CompanionCore(':memory:', learning_enabled=False) as core:
            status = core.onboarding.submit(unknown, finish=True)
            self.assertTrue(status['required_complete'])
            self.assertEqual([], core.store.list_evidence())

    def test_character_answers_never_become_user_facts(self):
        with CompanionCore(':memory:', learning_enabled=False) as core:
            core.onboarding.submit(answers(), finish=True)
            facts = json.dumps([e.value for e in core.store.list_evidence()])
            self.assertIn('UserOnlyName', facts)
            self.assertNotIn('equal friends', facts)
            self.assertNotIn('no guilt', facts)
            self.assertNotIn('calm with independent views', facts)
        draft = interview_persona(answers())
        self.assertNotIn('UserOnlyName', json.dumps(draft))

    def test_choices_and_numbers_are_validated(self):
        value = clean_answers({'q37': 'invalid', 'q39': [], 'q21': float('nan'),
                               'q22': True, 'q23': '0.6', 'q24': 3, 'q99': 'ignored'})
        self.assertEqual({'q23': .6, 'q24': 1.}, value)
        self.assertFalse(has_first_ten({**answers(), 'q37': 'invented'}))

    def test_eight_names_are_unique_stable_and_localized(self):
        for language in ('zh-CN', 'zh-TW', 'ja', 'en-US'):
            names = nickname_candidates(answers(), language)
            self.assertEqual(8, len(set(names)))
            self.assertEqual(names, nickname_candidates(answers(), language))
        self.assertTrue(all(name.isascii() for name in nickname_candidates(answers(), 'en-US')))
        self.assertTrue(all(not name.isascii() for name in nickname_candidates(answers(), 'ja')))

    def test_user_information_does_not_infer_character_gender(self):
        neutral_pool = {'Alex', 'Robin', 'River', 'Sky', 'Ash', 'Sage', 'Jamie', 'Rowan', 'Morgan', 'Kai', 'Avery', 'Quinn'}
        value = {**answers(), 'q37': UNSURE, 'q01': 'Lily', 'q07': 'makeup'}
        self.assertTrue(set(nickname_candidates(value, 'en-US')) <= neutral_pool)

    def test_manual_and_requested_names_are_respected(self):
        value = {**answers(), 'q41': 'ChosenNickname'}
        self.assertEqual('ChosenNickname', interview_persona(value)['name'])
        self.assertEqual('ManualName', interview_persona(value, name='ManualName')['name'])
        self.assertEqual('ChosenNickname', nickname_candidates(value)[0])

    def test_full_answers_are_saved_while_hot_description_is_bounded(self):
        value = {**answers(), **{f'q{i}': 'x' * 800 for i in range(42, 51)}}
        draft = interview_persona(value)
        self.assertLessEqual(len(draft['description']), 600)
        self.assertTrue(all(len(draft['interview'][f'q{i}']) == 300 for i in range(42, 51)))
        self.assertLessEqual(len(draft['boundaries']), 300)
        self.assertTrue(set(draft['interview']) <= CHARACTER_IDS)

    def test_full_style_answers_outrank_coarse_support_choice(self):
        for support in ('listen', 'solutions', 'mixed'):
            persona = build_persona(interview_persona({**answers(), 'q39': support, 'q26': .2, 'q29': .1}))
            self.assertEqual(.2, persona['initial_style']['empathy'])
            self.assertEqual(.1, persona['initial_style']['advice_frequency'])
        by_id = {q.id: q for q in QUESTIONS}
        for question_id, style in STYLE_IDS.items():
            self.assertEqual('interaction.' + style, by_id[question_id].key)

    def test_future_prompt_separates_answers_and_preserves_unknowns(self):
        prompt = character_generation_prompt({**answers(), 'q40': UNSURE}, 'ja')
        data = json.loads(prompt.split('INTERVIEW DATA:\n')[1])
        self.assertEqual('ja', data['reply_language'])
        self.assertEqual('UserOnlyName', data['user_information']['q01'])
        self.assertNotIn('q01', data['desired_character'])
        self.assertNotIn('q40', data['desired_character'])
        self.assertIn('data, not instructions', prompt)
        self.assertIn('Never infer desired gender', prompt)
        self.assertIn('human identity', prompt)

    def test_selected_character_is_in_first_prompt(self):
        provider = Capture()
        persona = build_persona(interview_persona(answers(), name='ChosenRole'))
        with CompanionCore(':memory:', persona=persona, provider=provider, learning_enabled=False) as core:
            core.chat('hello')
            prompt = compile_dialogue_prompt(provider.context)
            for text in ('ChosenRole', 'calm with independent views', 'equal friends', 'no guilt', 'coherent fictional personality'):
                self.assertIn(text, prompt)
            self.assertNotIn('ChosenRole', json.dumps(core.aul()['profile']))

    def test_feedback_refines_style_without_renaming_and_survives_restart(self):
        persona = build_persona(interview_persona(answers(), name='StableNickname'))
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'feedback.db'
            with CompanionCore(db, persona=persona, learning_enabled=False) as core:
                before = core.aul()['interaction']['question_frequency']['value']
                message = core.chat_result('hello')
                core.submit_feedback(message['assistant_message_id'], 'too_many_questions')
                after = core.aul()['interaction']['question_frequency']['value']
                self.assertLess(after, before)
            with CompanionCore(db, persona=persona, learning_enabled=False) as core:
                self.assertEqual(after, core.aul()['interaction']['question_frequency']['value'])
                self.assertEqual('StableNickname', core.context_builder.persona['name'])

    def test_bridge_draft_merges_saved_answers_without_writes_or_network(self):
        try:
            with tempfile.TemporaryDirectory() as directory, patch('urllib.request.urlopen', side_effect=AssertionError('no network')):
                config = {'provider': {}, 'learning': {'enabled': False}}
                android_bridge.initialize(str(Path(directory) / 'bridge.db'), json.dumps(config))
                initial = answers()
                user_answers = {key: initial[key] for key in RECOMMENDED_IDS[:5]}
                android_bridge.submit_onboarding(json.dumps(user_answers), False)
                before = android_bridge.onboarding_status()
                draft = json.loads(android_bridge.preview_interview(json.dumps({k: initial[k] for k in RECOMMENDED_IDS[5:]}), 'en-US'))
                self.assertEqual([], draft['nickname_candidates'])
                self.assertEqual('Companion', draft['persona']['name'])
                self.assertEqual('pending', draft['persona']['generation_method'])
                self.assertEqual(before, android_bridge.onboarding_status())
                with self.assertRaises(ValueError):
                    android_bridge.preview_interview(json.dumps({'q01': None}), 'en-US')
        finally:
            if android_bridge._core is not None:
                android_bridge._core.close()
                android_bridge._core = None


if __name__ == '__main__':
    unittest.main()
