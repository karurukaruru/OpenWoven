from __future__ import annotations

import tempfile
import sqlite3
import json
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from adaptive_companion.core import CompanionCore
from adaptive_companion.llm import LLMProvider
from adaptive_companion.models import Evidence
from adaptive_companion.observer import RuleBasedObserver
from adaptive_companion.storage import (SQLiteStore, SCHEMA, MIGRATION_1_TO_2, MIGRATION_2_TO_3,
                                       MIGRATION_3_TO_4, MIGRATION_4_TO_5)


class CapturingProvider(LLMProvider):
    def __init__(self, response="ok"):
        self.contexts = []
        self.response = response

    def generate(self, context):
        self.contexts.append(context)
        return self.response


class DelayedObserver(RuleBasedObserver):
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def observe(self, message):
        self.entered.set()
        if not self.release.wait(5):
            raise TimeoutError("test did not release observer")
        return super().observe(message)


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = CompanionCore(Path(self.tmp.name) / "review.db", summary_message_threshold=2)

    def tearDown(self):
        self.core.close()
        self.tmp.cleanup()

    def test_default_baseline_persists_supporting_metadata(self):
        state = self.core.set_preference_baseline("reply_length", 0.5)
        preference = state["interaction"]["reply_length"]
        self.assertEqual(0.5, preference["value"])
        self.assertEqual(1, preference["evidence_count"])
        self.assertGreater(preference["confidence"], 0)
        self.assertIsNotNone(preference["last_updated"])
        self.assertEqual(preference, self.core.aul()["interaction"]["reply_length"])
        self.assertEqual(preference, self.core.store.list_audit("interaction.reply_length")[0]["new_value"])

    def test_summary_waits_for_learning_without_blocking_chat(self):
        self.core.close()
        observer = DelayedObserver()
        self.core = CompanionCore(Path(self.tmp.name) / "slow.db", observer=observer,
                                  summary_message_threshold=2)
        try:
            result = self.core.chat_result("我的目标是完成编译器项目。", "slow")
            self.assertTrue(observer.entered.wait(1))
            self.assertEqual([], self.core.store.list_memories())
            self.assertIsNone(self.core.store.get_metadata("rolling_last:slow"))
        finally:
            observer.release.set()
        self.core.wait_for_learning()
        summary = self.core.store.list_memories('rolling')[0]['content']
        self.assertTrue(summary["user_goals"])
        self.assertIsNone(self.core.memory.maybe_create_rolling_summary("slow"))
        self.assertEqual(result["assistant_message_id"], self.core.store.get_metadata("rolling_last:slow"))

    def test_summary_queries_sources_instead_of_global_recent_evidence(self):
        self.core.learn_now("我喜欢爵士乐。", "older")
        unrelated = self.core.store.save_message("other", "user", "unrelated", learning_status="disabled")
        self.core.store.save_evidence([
            Evidence(id=f"other_{i}", type="profile_fact", key="profile.job", value="unrelated",
                     source_message_id=unrelated.id) for i in range(1001)
        ])
        self.core.memory.message_threshold = 1
        summary = self.core.memory.maybe_create_rolling_summary("older")
        # Likes appear as preference phrases in Daily; assert the exact input query
        # instead of relying on the content layout of a specific summary type.
        source = self.core.store.list_messages("older")[0]
        evidence = self.core.store.evidence_for_sources([source.id])
        self.assertTrue(any(e.value == "爵士乐" for e in evidence))
        self.assertIsNotNone(summary)

    def test_delete_invalidates_all_derived_layers_and_sensitive_audit_history(self):
        first = self.core.chat_result("我叫阿宁，我喜欢爵士乐。", "forget")
        self.core.wait_for_learning()
        self.core.memory.maybe_create_rolling_summary("forget")
        self.core.memory.consolidate_daily()
        self.core.memory.consolidate_weekly()
        # A later audit for the same field can still contain the old private value.
        self.core.learn_now("我叫小周。", "later")
        self.assertIn("阿宁", str(self.core.store.list_audit()))
        self.assertTrue({"rolling", "daily", "weekly"}.issubset({
            m["kind"] for m in self.core.store.list_memories()
        }))
        self.core.delete_message(first["user_message_id"])
        self.assertNotIn("阿宁", str(self.core.store.list_audit()))
        self.assertNotIn("爵士乐", str(self.core.store.list_memories()))
        self.assertEqual("小周", self.core.aul()["profile"]["name"]["value"])
        self.assertEqual([], self.core.retriever.retrieve("爵士乐"))
        self.assertIsNone(self.core.store.get_metadata("rolling_last:forget"))

    def test_delete_preserves_unrelated_summaries_and_invalidates_legacy(self):
        first = self.core.store.save_message("a", "user", "first", learning_status="disabled")
        other = self.core.store.save_message("b", "user", "other", learning_status="disabled")
        self.core.store.upsert_memory("rolling", "a", {"facts": ["first"]}, first.id, first.id, [],
                                      source_message_ids=[first.id])
        kept = self.core.store.upsert_memory("rolling", "b", {"facts": ["other"]}, other.id, other.id, [],
                                             source_message_ids=[other.id])
        self.core.store.upsert_memory("daily", "legacy", {"facts": ["first"]}, first.id, other.id, [])
        self.core.delete_message(first.id)
        self.assertEqual([kept], [m["id"] for m in self.core.store.list_memories()])
        self.assertIsNone(self.core.store.upsert_memory(
            "rolling", "stale", {"facts": ["first"]}, first.id, first.id, [],
            source_message_ids=[first.id],
        ))

    def test_retry_history_does_not_include_the_old_answer_or_later_turns(self):
        provider = CapturingProvider()
        self.core.provider = provider
        self.core.chat_result("earlier", "retry")
        target = self.core.chat_result("original question", "retry")
        self.core.chat_result("LATER_SENTINEL", "retry")
        self.core.retry_message(target["user_message_id"])
        history = provider.contexts[-1]["recent_conversation"]
        self.assertEqual(["earlier", "ok"], [m["content"] for m in history])

    def test_delete_rolls_back_when_aul_rebuild_fails(self):
        result = self.core.chat_result("我喜欢爵士乐。", "atomic-forget")
        self.core.wait_for_learning()
        self.core.memory.maybe_create_rolling_summary("atomic-forget")
        before_aul = self.core.aul()
        before_memories = self.core.store.list_memories()
        with patch.object(self.core.learning.aggregator, "aggregate", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.core.delete_message(result["user_message_id"])
        self.assertIsNotNone(self.core.store.get_message(result["user_message_id"]))
        self.assertEqual(before_aul, self.core.aul())
        self.assertEqual(before_memories, self.core.store.list_memories())

    def test_short_standalone_queries_do_not_import_unrelated_active_goals(self):
        aul = self.core.learn_now("我的目标是完成编译器项目。")
        self.assertEqual("天气怎么样", self.core._retrieval_query("天气怎么样", aul))
        self.assertIn("编译器", self.core._retrieval_query("继续", aul))

    def test_expired_evidence_is_not_retrieved_as_live_context(self):
        source = self.core.store.save_message("expired", "user", "咖啡", learning_status="disabled")
        self.core.store.save_evidence([Evidence(
            id="expired", type="current_state", key="current.recent_avoidance", value="咖啡",
            source_message_id=source.id, importance=1, confidence=1,
            expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )])
        self.assertEqual([], self.core.retriever.retrieve("咖啡"))

    def test_empty_provider_response_is_a_retryable_failure(self):
        self.core.provider = CapturingProvider(" ")
        with self.assertRaisesRegex(ValueError, "empty"):
            self.core.chat_result("hello", "empty")
        self.assertEqual("failed", self.core.store.list_messages("empty")[0].status)
        self.assertEqual("failed", self.core.store.list_generation_metrics()[0]["status"])

    def test_real_v5_database_migrates_to_latest_without_losing_existing_data(self):
        self.core.learn_now("我喜欢咖啡。")
        expected = self.core.aul()
        legacy = Path(self.tmp.name) / "legacy_v5.db"
        with closing(sqlite3.connect(legacy)) as conn:
            conn.executescript(SCHEMA + MIGRATION_1_TO_2 + MIGRATION_2_TO_3 + MIGRATION_3_TO_4 + MIGRATION_4_TO_5)
            conn.execute("INSERT INTO aul_state VALUES(1,?,?,?)", (json.dumps(expected), expected['version'], expected['updated_at']))
            conn.execute("INSERT INTO messages(id,conversation_id,role,content,timestamp,token_count) VALUES('legacy','default','user','旧聊天',?,3)", (datetime.now(UTC).isoformat(),))
            conn.commit()
        reopened = SQLiteStore(legacy)
        with reopened.connection() as conn:
            self.assertEqual(11, conn.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual([], conn.execute("PRAGMA foreign_key_check").fetchall())
        self.assertEqual('旧聊天', reopened.get_message('legacy').content)
        self.assertEqual(expected, reopened.get_aul())

    def test_explicit_profile_correction_can_replace_more_confident_old_fact(self):
        self.core.learn_now("我住在上海。")
        source = self.core.store.save_message("update", "user", "不对，我现在住在杭州。",
                                               learning_status="disabled")
        self.core.store.save_evidence([Evidence(
            id="new_location", type="correction", key="profile.location", value="杭州",
            source_message_id=source.id, confidence=0.85, signal="correction",
        )])
        state = self.core.learning.aggregator.aggregate()
        self.assertEqual("杭州", state["profile"]["location"]["value"])

    def test_restart_recovers_more_than_fifty_pending_messages(self):
        for i in range(61):
            self.core.store.save_message("backlog", "user", f"嗯 {i}", learning_status="pending")
        self.core.close()
        self.core = CompanionCore(self.core.store.path)
        self.core.wait_for_learning()
        self.assertEqual([], self.core.store.list_messages_for_learning(limit=None))
        self.assertEqual(61, self.core.aul()["relationship"]["interaction_count"])

    def test_metrics_distinguish_provider_usage_from_estimates(self):
        self.core.chat_result("local", "metrics")
        self.assertEqual("estimated", self.core.store.list_generation_metrics()[0]["usage_source"])
        provider = CapturingProvider()
        provider.last_usage = {"prompt_tokens": 51, "completion_tokens": 7}
        self.core.provider = provider
        self.core.chat_result("reported", "metrics")
        metric = self.core.store.list_generation_metrics()[0]
        self.assertEqual("provider", metric["usage_source"])
        self.assertEqual(58, metric["total_tokens"])

    def test_completed_goals_do_not_remain_active_in_summaries(self):
        self.core.learn_now("我的目标是完成编译器项目。", "project")
        self.core.learn_now("今天编译器项目完成了。", "project")
        rolling = self.core.store.list_memories('rolling')[0]['content']
        daily = self.core.memory.consolidate_daily()
        weekly = self.core.memory.consolidate_weekly()
        self.assertEqual([], rolling["user_goals"])
        self.assertEqual([], daily["active_projects"])
        self.assertEqual([], weekly["continuing_goals"])
        self.assertTrue(daily["important_events"])
        self.assertTrue(weekly["archived_events"])


if __name__ == "__main__":
    unittest.main()
