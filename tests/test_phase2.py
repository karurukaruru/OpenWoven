from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from adaptive_companion.core import CompanionCore
from adaptive_companion.context import estimate_tokens
from adaptive_companion.delivery import DeliveryPlanner, DeliverySettings
from adaptive_companion.llm import LLMProvider
from adaptive_companion.proactive import ProactiveSettings


class FailingProvider(LLMProvider):
    def generate(self, context):
        raise TimeoutError("network timeout")


class PhaseTwoCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "phase2.db"
        self.core = CompanionCore(self.db)

    def tearDown(self):
        self.core.close()
        self.tmp.cleanup()

    def test_feedback_updates_aul_and_next_policy(self):
        result = self.core.chat_result("解释一下这个问题。")
        before = self.core.aul()["interaction"]
        changed = self.core.submit_feedback(result["assistant_message_id"], "too_long")["aul"]
        changed = self.core.submit_feedback(result["assistant_message_id"], "too_many_questions")["aul"]
        self.assertLess(changed["interaction"]["reply_length"]["value"], before["reply_length"]["value"])
        self.assertLess(changed["interaction"]["question_frequency"]["value"], before["question_frequency"]["value"])
        policy = self.core.current_policy("继续聊")
        self.assertLess(policy["reply_length"], 0.5)
        self.assertLess(policy["question_frequency"], 0.5)
        self.assertEqual(2, len(self.core.store.list_feedback()))

    def test_feedback_is_deduplicated_and_initiative_maps_correctly(self):
        result = self.core.chat_result("聊聊下一步。")
        message_id = result["assistant_message_id"]
        before = self.core.aul()["interaction"]["initiative"]["value"]
        first = self.core.submit_feedback(message_id, "too_little_initiative")
        after = first["aul"]["interaction"]["initiative"]["value"]
        duplicate = self.core.submit_feedback(message_id, "too_little_initiative")
        self.assertGreater(after, before)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(after, duplicate["aul"]["interaction"]["initiative"]["value"])
        self.assertEqual(1, len(self.core.store.list_feedback()))

    def test_completed_periodic_feedback_does_not_count_as_dismissal(self):
        self.core.feedback.dismiss_periodic()
        self.core.feedback.complete_periodic()
        self.assertEqual("0", self.core.store.get_metadata("feedback_dismissals"))

    def test_proactive_intent_executes_and_saves_message(self):
        # This checks delivery, not quiet hours: force skips due time, never consent
        # or quiet-hour guards. Make the test independent of the local wall clock.
        self.core.proactive.settings.quiet_start_hour = 0
        self.core.proactive.settings.quiet_end_hour = 0
        result = self.core.chat_result("我明天下午考试，15点结束。", "exam-chat")
        scheduled_id = result["scheduled_message"]
        self.assertIsNotNone(scheduled_id)
        pending = self.core.store.get_scheduled_message(scheduled_id)
        self.assertEqual("pending", pending.status)
        sent = self.core.execute_scheduled(scheduled_id, force=True)
        self.assertTrue(sent["sent"])
        self.assertIn("考试", sent["text"])
        self.assertEqual("sent", self.core.store.get_scheduled_message(scheduled_id).status)
        self.assertEqual(sent["message_id"], self.core.store.get_scheduled_message(scheduled_id).sent_message_id)

    def test_resolved_topic_cancels_pending_proactive_message(self):
        first = self.core.chat_result("我明天下午考试，15点结束。", "cancel-chat")
        scheduled_id = first["scheduled_message"]
        self.core.chat("我考试考完了，挺好的。", "cancel-chat")
        self.assertEqual("cancelled", self.core.store.get_scheduled_message(scheduled_id).status)
        result = self.core.execute_scheduled(scheduled_id, force=True)
        self.assertFalse(result["sent"])

    def test_scheduled_message_survives_restart(self):
        result = self.core.chat_result("我明天下午面试。", "restart-chat")
        scheduled_id = result["scheduled_message"]
        self.core.close()
        self.core = CompanionCore(self.db)
        restored = self.core.store.get_scheduled_message(scheduled_id)
        self.assertIsNotNone(restored)
        self.assertEqual("pending", restored.status)

    def test_proactive_execution_rechecks_disabled_and_quiet_hours(self):
        result = self.core.chat_result("我明天下午考试，15点结束。", "guard-chat")
        scheduled_id = result["scheduled_message"]
        self.core.proactive.settings.enabled = False
        allowed, reason = self.core.proactive.revalidate(scheduled_id)
        self.assertFalse(allowed)
        self.assertEqual("proactive messages disabled", reason)
        self.assertEqual("cancelled", self.core.store.get_scheduled_message(scheduled_id).status)

        self.core.proactive.settings = ProactiveSettings(quiet_start_hour=22, quiet_end_hour=8)
        second = self.core.chat_result("我明天下午面试。", "quiet-chat")["scheduled_message"]
        allowed, reason = self.core.proactive.revalidate(
            second, datetime.now().astimezone().replace(hour=23, minute=0)
        )
        self.assertFalse(allowed)
        self.assertEqual("quiet hours", reason)
        self.assertEqual("pending", self.core.store.get_scheduled_message(second).status)

    def test_delivery_plan_splits_and_clamps_delays(self):
        planner = DeliveryPlanner(DeliverySettings(
            split_probability=1.0, minimum_delay_ms=300,
            maximum_delay_ms=900, maximum_parts=3,
        ))
        plan = planner.plan("哈哈，我大概明白了。不过后面那个地方得改一下。", "fixed")
        self.assertEqual("split", plan.mode)
        self.assertEqual(2, len(plan.parts))
        self.assertEqual(0, plan.parts[0].delay_ms)
        self.assertTrue(all(300 <= part.delay_ms <= 900 for part in plan.parts[1:]))

    def test_unsplit_delivery_has_no_post_model_delay(self):
        planner = DeliveryPlanner(DeliverySettings(split_probability=0.0))
        plan = planner.plan("A complete answer which should remain a single bubble.", "fixed")
        self.assertEqual("immediate", plan.mode)
        self.assertEqual(0, plan.parts[0].delay_ms)

    def test_successful_generation_records_local_latency_and_token_estimates(self):
        result = self.core.chat_result("记录一次性能数据。")
        metric = self.core.store.list_generation_metrics()[0]
        self.assertEqual("success", metric["status"])
        self.assertEqual(result["assistant_message_id"], metric["result_message_id"])
        self.assertGreater(metric["prompt_tokens"], 0)
        self.assertGreater(metric["completion_tokens"], 0)
        self.assertGreaterEqual(metric["latency_ms"], 0)

    def test_api_failure_keeps_user_message_for_retry(self):
        self.core.close()
        self.core = CompanionCore(self.db, provider=FailingProvider())
        with self.assertRaises(TimeoutError):
            self.core.chat("这条消息不能丢。", "offline")
        messages = self.core.store.list_messages("offline")
        self.assertEqual(1, len(messages))
        self.assertEqual("failed", messages[0].status)
        self.assertIn("timeout", messages[0].error)
        metric = self.core.store.list_generation_metrics()[0]
        self.assertEqual("failed", metric["status"])
        self.assertEqual("chat", metric["kind"])

    def test_pending_learning_recovers_after_restart_and_is_idempotent(self):
        message = self.core.store.save_message(
            "recovery", "user", "我喜欢爵士乐。", learning_status="pending",
        )
        self.core.close()
        self.core = CompanionCore(self.db)
        self.core.wait_for_learning()
        learned = self.core.store.get_message(message.id)
        first_evidence = self.core.store.list_evidence()
        self.assertEqual("complete", learned.learning_status)
        self.assertTrue(any(item.source_message_id == message.id for item in first_evidence))

        self.core.store.update_learning_status(message.id, "failed")
        self.core.close()
        self.core = CompanionCore(self.db)
        self.core.wait_for_learning()
        second_evidence = self.core.store.list_evidence()
        self.assertEqual(len(first_evidence), len(second_evidence))
        self.assertEqual("complete", self.core.store.get_message(message.id).learning_status)

    def test_deleting_user_message_cascades_reply_evidence_feedback_and_schedule(self):
        result = self.core.chat_result("我明天下午考试，15点结束，而且我喜欢爵士乐。", "delete-chat")
        self.core.wait_for_learning()
        self.core.submit_feedback(result["assistant_message_id"], "too_long")
        deleted = self.core.delete_message(result["user_message_id"])
        self.assertEqual(
            {result["user_message_id"], result["assistant_message_id"]},
            set(deleted["message_ids"]),
        )
        self.assertIn(result["scheduled_message"], deleted["scheduled_ids"])
        self.assertEqual([], self.core.store.list_messages("delete-chat"))
        self.assertEqual([], self.core.store.list_feedback())
        self.assertFalse(any(
            item.source_message_id in deleted["message_ids"]
            for item in self.core.store.list_evidence()
        ))
        self.assertEqual([], self.core.store.list_generation_metrics())
        self.assertIsNone(self.core.store.get_scheduled_message(result["scheduled_message"]))

    def test_list_messages_after_reads_only_unsummarized_tail(self):
        first = self.core.store.save_message("tail", "user", "first")
        second = self.core.store.save_message("tail", "assistant", "second")
        third = self.core.store.save_message("tail", "user", "third")
        self.assertEqual([second.id, third.id], [
            item.id for item in self.core.store.list_messages_after("tail", first.id)
        ])

    def test_interrupted_pending_send_becomes_retryable_after_restart(self):
        pending = self.core.store.save_message("interrupted", "user", "hello", status="pending")
        self.core.close()
        self.core = CompanionCore(self.db)
        recovered = self.core.store.get_message(pending.id)
        self.assertEqual("failed", recovered.status)
        self.assertIn("interrupted", recovered.error.lower())

    def test_reply_and_schedule_completion_are_atomic_state_transitions(self):
        user = self.core.store.save_message("atomic", "user", "hello", status="pending")
        assistant = self.core.store.complete_reply(user.id, "hi")
        self.assertEqual("sent", self.core.store.get_message(user.id).status)
        self.assertEqual(user.id, assistant.reply_to_id)

        scheduled_id = self.core.chat_result("我明天下午考试，15点结束。", "atomic-schedule")["scheduled_message"]
        scheduled_reply = self.core.store.complete_scheduled_delivery(scheduled_id, "考得怎么样？")
        completed = self.core.store.get_scheduled_message(scheduled_id)
        self.assertEqual("sent", completed.status)
        self.assertEqual(scheduled_reply.id, completed.sent_message_id)

    def test_onboarding_builds_initial_aul_without_llm_chat(self):
        status = self.core.onboarding.status()
        self.assertEqual(50, status["total"])
        self.assertEqual("not_started", status["state"])

        updated = self.core.onboarding.submit({
            "q01": "Mio",
            "q07": "AI, drawing",
            "q21": 0.2,
            "q22": 0.85,
        })
        aul = self.core.aul()
        self.assertEqual("in_progress", updated["state"])
        self.assertEqual("Mio", aul["profile"]["name"]["value"])
        self.assertEqual({"AI", "drawing"}, {item["value"] for item in aul["profile"]["interests"]})
        self.assertEqual(0.2, aul["interaction"]["reply_length"]["value"])
        self.assertEqual(0.85, aul["interaction"]["warmth"]["value"])
        self.assertEqual(0, self.core.store.count_messages(role="user"))

    def test_onboarding_is_resumable_and_skippable(self):
        self.core.onboarding.submit({"q01": "Mio", "q02": "20s"})
        self.core.close()
        self.core = CompanionCore(self.db)
        restored = self.core.onboarding.status()
        self.assertEqual(2, restored["answered"])
        self.assertEqual("Mio", restored["answers"]["q01"])
        skipped = self.core.onboarding.skip()
        self.assertEqual("skipped", skipped["state"])
        resumed = self.core.onboarding.begin()
        self.assertEqual("in_progress", resumed["state"])

    def test_reanswering_onboarding_question_replaces_old_evidence(self):
        self.core.onboarding.submit({"q07": "AI, drawing"})
        self.core.onboarding.submit({"q07": "music"})
        interests = {item["value"] for item in self.core.aul()["profile"]["interests"]}
        self.assertEqual({"music"}, interests)

    def test_admin_preference_baseline_survives_later_reaggregation(self):
        changed = self.core.set_preference_baseline("reply_length", 0.2)
        self.assertEqual(0.2, changed["interaction"]["reply_length"]["value"])
        result = self.core.chat_result("解释一下。")
        updated = self.core.submit_feedback(result["assistant_message_id"], "too_long")["aul"]
        self.assertLess(updated["interaction"]["reply_length"]["value"], 0.2)
        self.assertGreater(updated["interaction"]["reply_length"]["value"], 0.0)

    def test_all_preference_dimensions_reach_executable_prompt_instructions(self):
        self.core.set_preference_baseline("teasing", 0.9)
        self.core.set_preference_baseline("initiative", 0.9)
        self.core.set_preference_baseline("emoji_frequency", 0.9)
        aul = self.core.aul()
        policy = self.core.policy_builder.build("随便聊聊", aul)
        context = self.core.context_builder.build(aul, policy, "随便聊聊", [], [])
        instructions = " ".join(context["policy_instructions"])
        self.assertIn("teasing", instructions)
        self.assertIn("Proactively", instructions)
        self.assertIn("emoji", instructions)

    def test_populated_aul_has_a_hard_prompt_projection_budget(self):
        self.core.onboarding.submit({
            f"q{number:02d}": "很长的初始化资料" * 80
            for number in range(1, 21)
        })
        aul = self.core.aul()
        policy = self.core.policy_builder.build("继续", aul)
        context = self.core.context_builder.build(aul, policy, "继续", [], [], budget=400)
        self.assertLessEqual(estimate_tokens(context["user_context"]), 100)


if __name__ == "__main__":
    unittest.main()
