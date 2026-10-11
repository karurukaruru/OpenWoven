"""Offline before/after demonstration; no model, real profile or credentials."""
import json
from openwoven.user_learning import UserLearner


def main():
    with UserLearner(':memory:', user_id='synthetic-demo') as learner:
        before = learner.policy(['coding'])
        learner.observe({
            'event_id': 'example-1', 'source_id': 'synthetic-message-1',
            'kind': 'preference', 'scope': 'coding', 'key': 'explanation.order',
            'action': 'Show the patch before explaining the implementation.',
            'signal': 'explicit', 'session_id': 'example-session',
            'evidence': 'The user explicitly prefers patch-first coding replies.',
        }, expected_version=before['version'])
        applied = learner.policy(['coding'])
        rule = applied['rules'][0]
        learner.observe({
            'event_id': 'example-2', 'source_id': 'synthetic-feedback-2',
            'kind': 'feedback', 'rule_id': rule['id'], 'rule_revision': rule['revision'],
            'outcome': 'rejected',
            'evidence': 'The user says this presentation order was unhelpful.',
        }, expected_version=applied['version'])
        rejected = learner.policy(['coding'])
        learner.observe({
            'event_id': 'example-3', 'source_id': 'synthetic-message-3',
            'kind': 'preference', 'scope': 'coding', 'key': 'explanation.order',
            'action': 'Explain the reason for the change, then show the patch.',
            'signal': 'correction', 'session_id': 'example-session',
            'evidence': 'The user explicitly corrects the coding presentation order.',
        }, expected_version=rejected['version'])
        corrected = learner.policy(['coding'])
        learner.forget_rule('coding', 'explanation.order', expected_version=corrected['version'])
        print(json.dumps({
            'before': before, 'learned': applied, 'rejected': rejected,
            'corrected': corrected, 'writing': learner.policy(['writing']),
            'forgotten': learner.policy(['coding']),
        }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
