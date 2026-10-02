from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from adaptive_companion.context import ContextBuilder, estimate_tokens
from adaptive_companion.core import CompanionCore
from adaptive_companion.llm import LLMProvider, OpenAICompatibleProvider, compile_dialogue_prompt
from adaptive_companion.models import DEFAULT_PERSONA


class CapturingProvider(LLMProvider):
    def __init__(self):
        self.contexts = []

    def generate(self, context):
        self.contexts.append(context)
        return "ok"


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "core.db"
        self.core = CompanionCore(self.db, summary_message_threshold=4, summary_token_threshold=80)

    def tearDown(self):
        self.core.close()
        self.tmp.cleanup()

    def test_repeated_shorter_feedback_lowers_value_and_raises_confidence(self):
        initial = self.core.aul()["interaction"]["reply_length"]
        first = self.core.learn_now("回答短点。")
        second = self.core.learn_now("别扯这么多。")
        p1 = first["interaction"]["reply_length"]
        p2 = second["interaction"]["reply_length"]
        self.assertLess(p1["value"], initial["value"])
        self.assertLess(p2["value"], p1["value"])
        self.assertGreater(p2["confidence"], p1["confidence"])
        self.assertEqual(2, p2["evidence_count"])

    def test_strong_correction_has_auditable_change(self):
        state = self.core.learn_now("别每句话都问我问题。")
        pref = state["interaction"]["question_frequency"]
        self.assertLess(pref["value"], 0.35)
        audit = self.core.store.list_audit("interaction.question_frequency")
        self.assertTrue(audit)
        self.assertIsNotNone(audit[0]["evidence_id"])
        self.assertIsNotNone(audit[0]["source_message_id"])
        self.assertIn("weighted evidence", audit[0]["reason"])

    def test_one_word_acknowledgement_is_not_preference_evidence(self):
        before = self.core.aul()["interaction"]
        after = self.core.learn_now("嗯")["interaction"]
        self.assertEqual(before, after)
        self.assertEqual([], self.core.store.list_evidence())

    def test_new_explicit_correction_outweighs_older_preference(self):
        detailed = self.core.learn_now("我喜欢详细解释。")
        self.assertGreater(detailed["interaction"]["reply_length"]["value"], 0.5)
        corrected = self.core.learn_now("最近回答短一点就行。")
        self.assertLess(corrected["interaction"]["reply_length"]["value"], 0.5)
        evidence = self.core.store.list_evidence("interaction.reply_length")
        self.assertEqual({"increase", "decrease"}, {e.direction for e in evidence})

    def test_stable_like_and_current_avoidance_are_separate(self):
        self.core.learn_now("我喜欢咖啡。")
        state = self.core.learn_now("我最近不想喝咖啡。")
        likes = [x["value"] for x in state["profile"]["likes"]]
        self.assertIn("咖啡", likes)
        self.assertEqual("喝咖啡", state["current"]["recent_avoidance"]["value"])
        self.assertIn("expires_at", state["current"]["recent_avoidance"])

    def test_completed_project_clears_current_goal_but_keeps_event(self):
        active = self.core.learn_now("我的目标是完成信号处理项目。")
        self.assertIsNotNone(active["current"]["current_goal"])
        done = self.core.learn_now("今天信号处理项目完成了。")
        self.assertIsNone(done["current"]["current_goal"])
        self.assertTrue(done["current"]["recent_events"])

    def test_next_dialogue_uses_updated_policy(self):
        self.core.close()
        provider = CapturingProvider()
        self.core = CompanionCore(self.db, provider=provider)
        self.core.chat("别每句话都问我问题。")
        first_frequency = provider.contexts[-1]["interaction_policy"]["question_frequency"]
        self.core.wait_for_learning()
        self.core.chat("今天随便聊聊。")
        second_frequency = provider.contexts[-1]["interaction_policy"]["question_frequency"]
        self.assertLess(second_frequency, first_frequency)
        self.assertGreater(provider.contexts[-1]["interaction_policy"]["aul_version"], 0)

    def test_retrieves_related_week_old_memory(self):
        self.core.learn_now("上周信号处理项目完成了。")
        old = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        with self.core.store.connection() as conn:
            conn.execute("UPDATE evidence SET created_at=?", (old,))
            conn.commit()
        results = self.core.retriever.retrieve("信号处理项目怎么样", limit=5)
        self.assertTrue(any("信号处理" in item["text"] for item in results))

    def test_retrieval_does_not_dump_unrelated_recent_evidence(self):
        self.core.learn_now("我喜欢爵士乐。")
        results = self.core.retriever.retrieve("数据库索引怎么优化", limit=5)
        self.assertFalse(any("爵士乐" in item["text"] for item in results))

    def test_compression_pipeline_preserves_raw_messages(self):
        inputs = [
            "我叫小周。",
            "我的目标是完成编译器项目。",
            "我喜欢咖啡。",
            "今天编译器项目完成了。",
        ]
        for text in inputs:
            self.core.chat(text, "compression")
        self.core.wait_for_learning()
        before = self.core.store.count_messages("compression")
        rolling = self.core.memory.maybe_create_rolling_summary("compression")
        rolling_memories = self.core.store.list_memories("rolling")
        daily = self.core.memory.consolidate_daily()
        weekly = self.core.memory.consolidate_weekly()
        self.assertTrue(rolling is not None or rolling_memories)
        self.assertIsNotNone(daily)
        self.assertIsNotNone(weekly)
        self.assertEqual(before, self.core.store.count_messages("compression"))
        kinds = {m["kind"] for m in self.core.store.list_memories()}
        self.assertTrue({"rolling", "daily", "weekly"}.issubset(kinds))
        self.assertTrue(self.core.retriever.retrieve("编译器项目"))

    def test_concurrent_learning_has_no_lost_evidence_or_version_regression(self):
        messages = [self.core.store.save_message("parallel", "user", "回答短点。") for _ in range(20)]
        with ThreadPoolExecutor(max_workers=8) as executor:
            states = list(executor.map(lambda m: self.core.learning.process(m.id), messages))
        final = self.core.aul()
        pref = final["interaction"]["reply_length"]
        self.assertEqual(20, pref["evidence_count"])
        self.assertEqual(20, len(self.core.store.list_evidence("interaction.reply_length")))
        self.assertGreater(final["version"], 0)
        self.assertTrue(all(state["version"] <= final["version"] for state in states))

    def test_restart_preserves_aul_and_raw_memory(self):
        self.core.learn_now("我叫阿宁。")
        version = self.core.aul()["version"]
        count = self.core.store.count_messages()
        self.core.close()
        self.core = CompanionCore(self.db)
        self.assertEqual(version, self.core.aul()["version"])
        self.assertEqual("阿宁", self.core.aul()["profile"]["name"]["value"])
        self.assertEqual(count, self.core.store.count_messages())

    def test_context_budget_drops_optional_history_not_current_message(self):
        aul = self.core.aul()
        policy = self.core.policy_builder.build("现在的问题", aul)
        recent = [self.core.store.save_message("budget", "user", "旧消息" * 200)]
        context = ContextBuilder().build(aul, policy, "现在的问题", recent, [], budget=10)
        self.assertEqual("现在的问题", context["current_user_message"])
        self.assertEqual([], context["recent_conversation"])

    def test_compact_prompt_uses_under_sixty_percent_of_naive_prompt(self):
        self.core.learn_now("我叫小周，我现在是电子信息专业。")
        self.core.learn_now("我喜欢咖啡。")
        self.core.learn_now("回答短点，直接点，别每句话都问我问题。")
        for index in range(4):
            self.core.store.save_message("tokens", "user", f"之前的对话内容 {index}：讨论信号处理项目。")
            self.core.store.save_message("tokens", "assistant", f"这是对应的历史回复 {index}。")
        current = self.core.store.save_message("tokens", "user", "请给我一个落地建议。")
        aul = self.core.aul()
        policy = self.core.policy_builder.build(current.content, aul)
        recent = self.core.store.list_messages("tokens", limit=20)
        compact = self.core.context_builder.build(
            aul, policy, current.content, recent, [], budget=3000,
            current_message_id=current.id,
        )
        compact_prompt = compile_dialogue_prompt(compact)
        naive_prompt = json.dumps({
            "persona": DEFAULT_PERSONA,
            "aul": {
                "profile": aul["profile"], "interaction": aul["interaction"],
                "relationship": aul["relationship"], "version": aul["version"],
            },
            "current_state": aul["current"],
            "interaction_policy": policy,
            "recent_conversation": [
                {"role": item.role, "content": item.content, "timestamp": item.timestamp}
                for item in recent
            ],
        }, ensure_ascii=False)
        self.assertLessEqual(estimate_tokens(compact_prompt), estimate_tokens(naive_prompt) * 0.60)
        self.assertIn("小周", compact_prompt)
        self.assertNotIn(current.content, compact_prompt)
        self.assertNotIn("question_frequency", compact_prompt)

    def test_output_budget_tracks_learned_reply_length(self):
        provider = OpenAICompatibleProvider("https://example.invalid/v1", "secret", "model", max_tokens=800)
        context = {"interaction_policy": {"reply_length": 0.2}}
        short_budget = provider._output_budget(context)
        context["interaction_policy"]["reply_length"] = 0.8
        long_budget = provider._output_budget(context)
        self.assertGreaterEqual(short_budget, 96)
        self.assertLess(short_budget, long_budget)
        self.assertLessEqual(long_budget, 800)
        provider._record_usage({"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60})
        provider._record_usage({"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48})
        self.assertEqual(108, provider.total_usage["total_tokens"])


if __name__ == "__main__":
    unittest.main()
