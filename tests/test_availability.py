from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from adaptive_companion.core import CompanionCore
from adaptive_companion.delivery import DeliverySettings
from adaptive_companion.proactive import ProactiveSettings


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "companion.db"
        self.core = CompanionCore(self.db, learning_enabled=False,
            delivery_settings=DeliverySettings(greeting_delay_enabled=True),
            proactive_settings=ProactiveSettings(quiet_start_hour=0, quiet_end_hour=0),
            memory_utc_offset_minutes=480)

    def tearDown(self):
        self.core.close()
        self.temp.cleanup()

    def test_greeting_is_durable_and_makes_no_early_model_call(self):
        with patch.object(self.core.provider, 'generate', side_effect=AssertionError('too early')):
            result = self.core.chat_result('在吗？')
        self.assertTrue(result['deferred'])
        self.assertEqual('', result['response'])
        item = self.core.store.get_scheduled_message(result['scheduled_message'])
        seconds = (datetime.fromisoformat(item.scheduled_at) - datetime.now().astimezone()).total_seconds()
        self.assertTrue(59 <= seconds <= 180)
        self.assertEqual('waiting', self.core.store.get_message(result['user_message_id']).status)
        self.assertEqual('not due', self.core.execute_scheduled(item.id)['reason'])
        self.core.close()
        self.core = CompanionCore(self.db, learning_enabled=False)
        self.assertEqual('waiting', self.core.store.get_message(result['user_message_id']).status)
        # User-initiated replies are not blocked by unsolicited-message limits/quiet hours.
        self.core.proactive.settings.enabled = False
        sent = self.core.execute_scheduled(item.id, force=True)
        self.assertTrue(sent['sent'])
        self.assertEqual(result['user_message_id'], self.core.store.get_message(sent['message_id']).reply_to_id)
        self.assertEqual('sent', self.core.store.get_message(result['user_message_id']).status)
        self.assertFalse(self.core.execute_scheduled(item.id, force=True)['sent'])

    def test_new_content_supersedes_waiting_greeting(self):
        first = self.core.chat_result('在吗')
        second = self.core.chat_result('我有个高数问题，请帮忙')
        self.assertFalse(second.get('deferred', False))
        self.assertEqual('cancelled', self.core.store.get_scheduled_message(first['scheduled_message']).status)
        self.assertFalse(self.core.execute_scheduled(first['scheduled_message'], force=True)['sent'])

    def test_in_progress_chat_and_actual_questions_are_not_delayed(self):
        for text in ('在吗？我很难受', '在吗，能帮我解释积分吗', '救命', '我今天考试了'):
            self.assertFalse(self.core.chat_result(text).get('deferred', False))
        self.assertFalse(self.core.chat_result('在吗').get('deferred', False))

    def test_delay_can_be_disabled(self):
        self.core.delivery.settings.greeting_delay_enabled = False
        self.assertFalse(self.core.chat_result('在吗').get('deferred', False))

    def test_retry_cancels_queue_and_replies_immediately(self):
        first = self.core.chat_result('在吗')
        retried = self.core.retry_message(first['user_message_id'])
        self.assertTrue(retried['response'])
        self.assertEqual('cancelled', self.core.store.get_scheduled_message(first['scheduled_message']).status)

    def test_expired_greeting_is_retryable_not_sent_late(self):
        first = self.core.chat_result('在吗')
        with self.core.store.connection() as conn:
            conn.execute('UPDATE scheduled_messages SET latest_at=? WHERE id=?',
                         ((datetime.now().astimezone() - timedelta(minutes=1)).isoformat(), first['scheduled_message']))
            conn.commit()
        self.assertEqual('expired', self.core.execute_scheduled(first['scheduled_message'])['reason'])
        self.assertEqual('failed', self.core.store.get_message(first['user_message_id']).status)

    def test_cancel_during_generation_cannot_commit_old_greeting(self):
        first = self.core.chat_result('在吗')
        def generate(context):
            self.core.delayed_replies.cancel_for_conversation('default')
            return '在'
        with patch.object(self.core.provider, 'generate', side_effect=generate):
            result = self.core.execute_scheduled(first['scheduled_message'], force=True)
        self.assertFalse(result['sent'])
        self.assertEqual([], self.core.store.list_messages(role='assistant'))

    def test_unknown_exam_date_is_remembered_and_asked_once(self):
        first = self.core.chat_result('我过段时间要高数考试了')
        self.assertIsNone(first['scheduled_message'])
        self.assertIn('是哪天、几点结束', first['response'])
        events = [m for m in self.core.store.list_memories('long_term') if m['content'].get('event_type')]
        self.assertEqual('awaiting_time', events[0]['content']['status'])
        self.assertIsNone(events[0]['content']['end_at'])
        second = self.core.chat_result('高数考试要准备一下')
        self.assertNotIn('是哪天、几点结束', second['response'])
        dated = self.core.chat_result('明天，下午3点结束')
        item = self.core.store.get_scheduled_message(dated['scheduled_message'])
        self.assertEqual(15, datetime.fromisoformat(item.scheduled_at).hour)
        self.assertEqual(45, datetime.fromisoformat(item.scheduled_at).minute)
        self.assertIn('高数考试', item.draft_intent)
        self.assertEqual(3, len(item.source_memory_ids))

    def test_date_only_does_not_guess_exam_end(self):
        result = self.core.chat_result('我明天下午高数考试')
        self.assertIsNone(result['scheduled_message'])
        self.assertIn('几点结束', result['response'])

    def test_unrelated_time_answer_and_invalid_date_do_not_fill_exam_slot(self):
        self.core.chat_result('我过段时间高数考试')
        self.assertIsNone(self.core.chat_result('我明天上班，17点结束')['scheduled_message'])
        self.assertIsNone(self.core.chat_result('2027-02-30高数考试，15点结束')['scheduled_message'])
        self.assertIsNotNone(self.core.chat_result('明天，15点结束')['scheduled_message'])

    def test_subject_specific_completion_preserves_another_exam(self):
        self.core.proactive.settings.max_per_day = 5
        first = self.core.chat_result('明天高数考试，15点结束')
        second = self.core.chat_result('后天英语考试，15点结束')
        self.core.chat_result('高数考试考完了')
        self.assertEqual('cancelled', self.core.store.get_scheduled_message(first['scheduled_message']).status)
        self.assertEqual('pending', self.core.store.get_scheduled_message(second['scheduled_message']).status)

    def test_explicit_care_cancellation_prevents_exam_followup(self):
        first = self.core.chat_result('明天高数考试，15点结束')
        self.core.chat_result('别提醒我高数考试')
        self.assertEqual('cancelled', self.core.store.get_scheduled_message(first['scheduled_message']).status)

    def test_completion_of_a_different_subject_does_not_close_the_only_known_exam(self):
        first = self.core.chat_result('明天高数考试，15点结束')
        self.core.chat_result('英语考试考完了')
        self.assertEqual('pending', self.core.store.get_scheduled_message(first['scheduled_message']).status)
        event = self.core.store.list_memories('long_term')[0]['content']
        self.assertEqual('confirmed', event['status'])

    def test_manual_queue_cancellation_leaves_a_retryable_message(self):
        first = self.core.chat_result('在吗')
        self.core.store.update_scheduled_status(first['scheduled_message'], 'cancelled')
        self.assertEqual('failed', self.core.store.get_message(first['user_message_id']).status)

    def test_start_time_is_not_mistaken_for_end_time(self):
        result = self.core.chat_result('我明天高数考试，下午3点开始')
        self.assertIsNone(result['scheduled_message'])

    def test_time_change_cancels_previous_followup_and_deletion_clears_sources(self):
        first = self.core.chat_result('明天高数考试，15点结束')
        second = self.core.chat_result('高数考试改到后天，16点结束')
        self.assertEqual('cancelled', self.core.store.get_scheduled_message(first['scheduled_message']).status)
        item = self.core.store.get_scheduled_message(second['scheduled_message'])
        self.assertEqual(16, datetime.fromisoformat(item.scheduled_at).hour)
        self.core.delete_message(first['user_message_id'])
        self.assertIsNone(self.core.store.get_scheduled_message(item.id))
        self.assertEqual([], self.core.store.list_memories('long_term'))

    def test_quoted_third_person_hypothetical_and_past_do_not_schedule(self):
        for text in ('他明天高数考试，15点结束', '假如我明天高数考试，15点结束',
                     '他说“明天高数考试，15点结束”', '我昨天高数考试，15点结束',
                     '我明天高数考试，15点结束，别提醒我'):
            self.assertIsNone(self.core.chat_result(text, text)['scheduled_message'])

    def test_complete_exam_cancels_followup(self):
        first = self.core.chat_result('我明天高数考试，15点结束')
        self.core.chat_result('高数考试考完了')
        self.assertEqual('cancelled', self.core.store.get_scheduled_message(first['scheduled_message']).status)

    def test_blank_or_invalid_onboarding_does_not_become_evidence(self):
        result = self.core.onboarding.submit({'q01': '', 'q21': float('nan'), 'q22': True, 'q23': 'oops'}, finish=True)
        self.assertEqual('completed', result['state'])
        self.assertEqual(0, result['answered'])
        self.assertEqual([], self.core.store.list_evidence())

    def test_quick_setup_and_empty_finish(self):
        result = self.core.onboarding.submit({'q01': 'Mio', 'q21': 0.2}, finish=True)
        self.assertEqual(2, result['answered'])
        self.assertEqual(["q01", "q06", "q07", "q11", "q19", "q36", "q37", "q38", "q39", "q40"], result['recommended_ids'])
        self.core.onboarding.begin()
        self.assertEqual('completed', self.core.onboarding.submit({}, finish=True)['state'])

    def test_clearing_answer_withdraws_evidence(self):
        self.core.onboarding.submit({'q01': 'Mio', 'q21': 0.2})
        result = self.core.onboarding.submit({'q01': None, 'q21': None})
        self.assertEqual(0, result['answered'])
        self.assertEqual([], self.core.store.list_evidence())

    def test_onboarding_rolls_back_evidence_and_progress_together(self):
        self.core.onboarding.submit({'q01': 'Mio'})
        before = self.core.onboarding.status()
        with patch.object(self.core.onboarding.aggregator, 'aggregate', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                self.core.onboarding.submit({'q01': 'Other'})
        self.assertEqual(before['answers'], self.core.onboarding.status()['answers'])
        self.assertEqual('Mio', self.core.store.list_evidence()[0].value)


if __name__ == '__main__':
    unittest.main()
