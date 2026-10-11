from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from openwoven.user_learning import UserLearner, VersionConflict

ROOT = Path(__file__).resolve().parents[1]


def event(n, **changes):
    return dict(event_id=f'event-{n}', source_id=f'message-{n}', kind='preference',
                scope='coding', key='explanation.order', action='Show the patch before the explanation.',
                signal='explicit', session_id='session-a', evidence='User prefers patch-first coding replies.', **changes)


class UserLearningTests(unittest.TestCase):
    def setUp(self):
        self.learner = UserLearner(':memory:', 'synthetic-user')

    def tearDown(self):
        self.learner.close()

    def send(self, n, **changes):
        e = event(n)
        e.update(changes)
        self.learner.observe(e, expected_version=self.learner.version)
        return e

    def feedback(self, n, outcome='accepted', rule=None):
        rule = rule or self.learner.inspect()['rules'][0]
        e = dict(event_id=f'feedback-{n}', source_id=f'feedback-source-{n}', kind='feedback',
                 rule_id=rule['id'], rule_revision=rule['revision'], outcome=outcome,
                 evidence='User explicitly evaluated this behavior.')
        return self.learner.observe(e, expected_version=self.learner.version)

    def test_explicit_policy_is_scoped_and_frozen(self):
        self.send(1)
        frozen = self.learner.policy(['coding'])
        self.assertEqual(len(frozen['rules']), 1)
        self.assertEqual(self.learner.policy(['writing'])['rules'], [])
        self.send(2, signal='correction', action='Explain the reasoning before the patch.')
        self.assertIn('patch before', frozen['rules'][0]['action'])
        self.assertIn('reasoning before', self.learner.policy(['coding'])['rules'][0]['action'])

    def test_inference_requires_two_sessions_and_unique_sources(self):
        self.send(1, signal='inferred')
        self.send(2, signal='inferred')
        self.assertEqual(self.learner.policy(['coding'])['rules'], [])
        self.send(3, signal='inferred', session_id='session-b', source_id='message-1')
        self.assertEqual(self.learner.policy(['coding'])['rules'], [])
        self.send(4, signal='inferred', session_id='session-b')
        self.assertEqual(len(self.learner.policy(['coding'])['rules']), 1)

    def test_explicit_preference_survives_inferred_contradictions(self):
        self.send(1)
        for n in range(2, 5):
            self.send(n, signal='inferred', session_id=f'session-{n}', action='Explain first.')
        self.assertIn('patch before', self.learner.policy(['coding'])['rules'][0]['action'])

    def test_unconfirmed_scoped_candidate_does_not_hide_general_rule(self):
        self.send(1, scope='general', action='Brief replies.')
        self.send(2, signal='inferred', action='Detailed coding replies.')
        self.assertEqual(self.learner.policy(['coding'])['rules'][0]['action'], 'Brief replies.')

    def test_targeted_feedback_and_correction(self):
        self.send(1)
        old_rule = self.learner.inspect()['rules'][0]
        self.feedback(1)
        self.feedback(2, 'rejected')
        self.assertEqual(self.learner.policy(['coding'])['rules'], [])
        self.assertEqual(self.learner.inspect()['rules'][0]['outcomes'], {'accepted': 1, 'rejected': 1})
        self.send(2, signal='correction', action='Explain first.')
        with self.assertRaises(VersionConflict):
            self.feedback(3, rule=old_rule)
        self.assertEqual(self.learner.policy(['coding'])['rules'][0]['action'], 'Explain first.')

    def test_corroboration_preserves_feedback_and_cannot_reenable_rejection(self):
        self.send(1, signal='inferred')
        self.send(2, signal='inferred', session_id='session-b')
        self.feedback(1)
        revision = self.learner.inspect()['rules'][0]['revision']
        self.send(3, signal='inferred', session_id='session-c')
        self.assertEqual(self.learner.inspect()['rules'][0]['revision'], revision)
        self.assertEqual(self.learner.inspect()['rules'][0]['outcomes']['accepted'], 1)
        self.feedback(2, 'rejected')
        self.send(4, signal='inferred', session_id='session-d', action='Explain first.')
        self.send(5, signal='inferred', session_id='session-e', action='Explain first.')
        self.assertEqual(self.learner.policy(['coding'])['rules'], [])

    def test_expiration_and_scope_precedence(self):
        self.send(1, scope='general', action='Brief replies.')
        self.send(2, action='Detailed code explanations.')
        self.send(3, scope='project:demo', action='Use a worked example.')
        policy = self.learner.policy(['coding', 'project:demo'])
        self.assertEqual(policy['rules'][0]['action'], 'Use a worked example.')
        self.send(4, scope='study', key='study.format', expires_at=(datetime.now(UTC)-timedelta(seconds=1)).isoformat())
        self.assertFalse(any(r['key'] == 'study.format' for r in self.learner.inspect()['rules']))
        self.feedback(1, 'rejected', self.learner.inspect()['rules'][1])
        self.assertEqual(self.learner.policy(['coding'])['rules'], [])

    def test_duplicate_retry_conflict_and_payload_collision(self):
        e = self.send(1)
        self.assertTrue(self.learner.observe(e, expected_version=0)['duplicate'])
        with self.assertRaises(VersionConflict):
            self.learner.observe(event(2), expected_version=0)
        with self.assertRaises(ValueError):
            self.learner.observe({**e, 'action': 'Different'}, expected_version=1)
        self.assertEqual(self.learner.version, 1)

    def test_forget_source_replays_and_forget_rule_removes_all_revisions(self):
        self.send(1)
        self.send(2, signal='correction', action='Explain first.')
        self.feedback(1)
        result = self.learner.forget('message-2', expected_version=3)
        self.assertEqual(result['removed_events'], 2)
        self.assertIn('patch before', self.learner.policy(['coding'])['rules'][0]['action'])
        self.send(3, action='Explain first.')
        self.learner.forget_rule('coding', 'explanation.order', expected_version=self.learner.version)
        self.assertEqual(self.learner.inspect()['rules'], [])

    def test_deleting_support_demotes_inference(self):
        self.send(1, signal='inferred')
        self.send(2, signal='inferred', session_id='session-b')
        self.learner.forget('message-1', expected_version=2)
        self.assertEqual(self.learner.policy(['coding'])['rules'], [])
        self.assertEqual(self.learner.inspect()['rules'][0]['status'], 'candidate')

    def test_schema_rejects_ambiguous_feedback_and_unbounded_text(self):
        for update in ({'signal': 'silence'}, {'signal': []}, {'kind': []}, {'evidence': 'x'*361}, {'action': 'x'*241},
                       {'expires_at': '2026-01-01'}, {'scope': '../outside'}, {'unknown': True}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.learner.observe({**event(1), **update}, expected_version=0)
        self.send(1)
        with self.assertRaises(ValueError):
            self.feedback(1, 'thumb_up')

    def test_budget_and_explanation_keep_evidence_out_of_hot_context(self):
        for n in range(10):
            self.send(n, key=f'workflow.{n}', action='x'*240)
        policy = self.learner.policy(['coding'], max_chars=700, max_rules=2)
        self.assertLessEqual(len(json.dumps(policy, ensure_ascii=False)), 700)
        self.assertLessEqual(len(policy['rules']), 2)
        self.assertNotIn('evidence', json.dumps(policy))
        explanation = self.learner.explain('coding|workflow.9')
        self.assertEqual(explanation['evidence'][0]['source_id'], 'message-9')

    def test_restart_identity_and_two_writer_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'synthetic.db'
            with UserLearner(path, 'one') as first, UserLearner(path, 'one') as second:
                def run(pair):
                    learner, n = pair
                    try:
                        learner.observe(event(n), expected_version=0)
                        return 'saved'
                    except VersionConflict:
                        return 'conflict'
                with ThreadPoolExecutor(2) as pool:
                    results = list(pool.map(run, [(first, 1), (second, 2)]))
                self.assertCountEqual(results, ['saved', 'conflict'])
            with UserLearner(path, 'one') as reopened:
                self.assertEqual(reopened.version, 1)
                self.assertEqual(len(reopened.policy(['coding'])['rules']), 1)
            with self.assertRaises(ValueError):
                UserLearner(path, 'two')

    def test_portable_cli_offline_and_sdk_match(self):
        script = ROOT/'skills/agent-user-learning/scripts/aul.py'
        self.assertEqual(script.read_bytes(), (ROOT/'src/openwoven/user_learning.py').read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            args = [sys.executable, '-I', str(script), '--db', str(Path(tmp)/'test.db'), '--user-id', 'synthetic']
            input_path = Path(tmp)/'event.json'
            input_path.write_text(json.dumps({'expected_version': 0, 'event': event(1)}), encoding='utf-8')
            for command in (['observe', '--input', str(input_path)], ['policy', '--scope', 'coding'], ['explain', '--rule-id', 'coding|explanation.order'], ['forget-rule', '--scope', 'coding', '--key', 'explanation.order', '--expected-version', '1']):
                result = subprocess.run(args+command, cwd=tmp, capture_output=True, text=True, check=True)
                self.assertIsInstance(json.loads(result.stdout), dict)


if __name__ == '__main__':
    unittest.main()
