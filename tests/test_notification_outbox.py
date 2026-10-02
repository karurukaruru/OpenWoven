from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from adaptive_companion import android_bridge
from adaptive_companion.core import CompanionCore
from adaptive_companion.proactive import ProactiveSettings


def offline_core(path=':memory:'):
    return CompanionCore(path, learning_enabled=False,
                         proactive_settings=ProactiveSettings(quiet_start_hour=0, quiet_end_hour=0))


def deliver(core, text='合成定时消息'):
    item = core.schedule_custom(text, (datetime.now(UTC) + timedelta(minutes=10)).isoformat())
    return item, core.execute_scheduled(item['id'], force=True)


class NotificationOutboxTests(unittest.TestCase):
    def test_commit_queues_notification_and_retry_never_generates_another_reply(self):
        with offline_core() as core:
            item, result = deliver(core)
            self.assertEqual([{'message_id': result['message_id'], 'created_at':
                core.store.get_message(result['message_id']).timestamp, 'text': result['text']}],
                core.store.pending_notifications())
            self.assertEqual('sent', core.store.get_scheduled_message(item['id']).status)
            self.assertFalse(core.execute_scheduled(item['id'], force=True)['sent'])
            self.assertEqual(1, core.store.count_messages(role='assistant'))
            self.assertEqual([], core.store.list_generation_metrics())

    def test_process_restart_recovers_notification_for_already_sent_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'synthetic.db'
            with offline_core(path) as core:
                item, result = deliver(core)
            with offline_core(path) as restarted:
                self.assertEqual(result['message_id'], restarted.store.pending_notifications()[0]['message_id'])
                self.assertFalse(restarted.execute_scheduled(item['id'], force=True)['sent'])
                self.assertTrue(restarted.store.finish_notification(result['message_id'], 'submitted'))
                self.assertEqual([], restarted.store.pending_notifications())
                self.assertEqual(1, restarted.store.count_messages(role='assistant'))

    def test_outbox_insert_failure_rolls_back_message_plan_and_job_together(self):
        with offline_core() as core:
            item = core.schedule_custom('rollback', (datetime.now(UTC) + timedelta(minutes=10)).isoformat())
            with core.store.connection() as conn:
                conn.execute("""CREATE TRIGGER synthetic_notification_failure BEFORE INSERT ON notification_outbox
                    BEGIN SELECT RAISE(ABORT,'synthetic failure'); END""")
                conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                core.execute_scheduled(item['id'], force=True)
            self.assertEqual('pending', core.store.get_scheduled_message(item['id']).status)
            self.assertEqual(0, core.store.count_messages(role='assistant'))
            self.assertEqual([], core.store.pending_notifications())
            with core.store.connection() as conn:
                self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM message_delivery_plans').fetchone()[0])

    def test_acknowledgement_is_idempotent_and_cannot_relabel_a_handled_message(self):
        with offline_core() as core:
            _, result = deliver(core)
            self.assertTrue(core.store.finish_notification(result['message_id'], 'submitted'))
            self.assertFalse(core.store.finish_notification(result['message_id'], 'disabled'))
            self.assertFalse(core.store.finish_notification('missing', 'submitted'))
            with core.store.connection() as conn:
                self.assertEqual('submitted', conn.execute('SELECT status FROM notification_outbox').fetchone()[0])

    def test_invalid_acknowledgements_do_not_claim_read_receipts(self):
        with offline_core() as core:
            _, result = deliver(core)
            for status in ('pending', 'delivered', 'read', 'expired', ''):
                with self.assertRaises(ValueError):
                    core.store.finish_notification(result['message_id'], status)
            self.assertEqual(1, len(core.store.pending_notifications()))

    def test_foreground_and_disabled_notifications_are_not_replayed(self):
        with offline_core() as core:
            for status in ('foreground', 'disabled'):
                _, result = deliver(core, status)
                self.assertTrue(core.store.finish_notification(result['message_id'], status))
            self.assertEqual([], core.store.pending_notifications())
            self.assertEqual(2, core.store.count_messages(role='assistant'))

    def test_expiry_keeps_raw_chat_but_prevents_stale_notification_replay(self):
        with offline_core() as core:
            _, result = deliver(core)
            old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
            with core.store.connection() as conn:
                conn.execute('UPDATE notification_outbox SET created_at=?', (old,))
                conn.commit()
            self.assertEqual([], core.store.pending_notifications())
            self.assertFalse(core.store.finish_notification(result['message_id'], 'submitted'))
            self.assertIsNotNone(core.store.get_message(result['message_id']))
            with core.store.connection() as conn:
                self.assertEqual('expired', conn.execute('SELECT status FROM notification_outbox').fetchone()[0])

    def test_delete_removes_pending_and_submitted_notification_rows(self):
        with offline_core() as core:
            for status in ('pending', 'submitted'):
                _, result = deliver(core)
                if status != 'pending':
                    core.store.finish_notification(result['message_id'], status)
                core.delete_message(result['message_id'])
            with core.store.connection() as conn:
                self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0])
                self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())

    def test_clear_history_also_clears_notification_outbox(self):
        with offline_core() as core:
            deliver(core)
            core.store.clear_user_data()
            self.assertEqual([], core.store.pending_notifications())
            with core.store.connection() as conn:
                self.assertEqual(0, conn.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0])

    def test_pending_read_is_bounded_and_does_not_consume_a_notification(self):
        with offline_core() as core:
            for i in range(5):
                deliver(core, 'synthetic ' + str(i))
            self.assertEqual(2, len(core.store.pending_notifications(2)))
            self.assertEqual(1, len(core.store.pending_notifications(0)))
            self.assertEqual(5, len(core.store.pending_notifications(1000)))
            self.assertEqual(5, len(core.store.pending_notifications()))

    def test_v9_upgrade_preserves_history_without_replaying_legacy_sent_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'v9.db'
            with offline_core(path) as core:
                item, result = deliver(core)
                with core.store.connection() as conn:
                    conn.execute('DROP TABLE notification_outbox')
                    conn.execute('PRAGMA user_version=9')
                    conn.commit()
            with offline_core(path) as upgraded:
                self.assertEqual('sent', upgraded.store.get_scheduled_message(item['id']).status)
                self.assertEqual(result['text'], upgraded.store.get_message(result['message_id']).content)
                self.assertEqual([], upgraded.store.pending_notifications())
                self.assertEqual(result['delivery_plan'], upgraded.store.delivery_plans_for([result['message_id']])[result['message_id']])
                with upgraded.store.connection() as conn:
                    self.assertEqual(11, conn.execute('PRAGMA user_version').fetchone()[0])
                    self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())

    def test_bridge_exposes_queue_notification_state_and_validated_acknowledgement(self):
        with offline_core() as core, patch.object(android_bridge, '_core', core):
            _, result = deliver(core)
            self.assertEqual('pending', json.loads(android_bridge.scheduled_queue())[0]['notification_status'])
            self.assertEqual(result['message_id'], json.loads(android_bridge.pending_notifications(1))[0]['message_id'])
            self.assertTrue(android_bridge.finish_notification(result['message_id'], 'submitted'))
            self.assertEqual('submitted', json.loads(android_bridge.scheduled_queue())[0]['notification_status'])
            self.assertEqual([], json.loads(android_bridge.pending_notifications()))


if __name__ == '__main__':
    unittest.main()
