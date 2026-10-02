from __future__ import annotations

import json
import unittest

from adaptive_companion.models import Evidence, Message, utc_now
from adaptive_companion.semantic_observer import (
    HybridObserver,
    OpenAICompatibleEvidenceObserver,
)


def message(text: str) -> Message:
    return Message("msg_test", "test", "user", text, utc_now(), 10)


class FakeSemanticObserver:
    def __init__(self, items=None, error: Exception | None = None):
        self.items = items or []
        self.error = error
        self.calls = 0

    def observe(self, source: Message):
        self.calls += 1
        if self.error:
            raise self.error
        return self.items


class SemanticObserverTests(unittest.TestCase):
    def test_acknowledgement_and_understood_correction_cost_zero_calls(self):
        semantic = FakeSemanticObserver()
        hybrid = HybridObserver(semantic)
        self.assertEqual([], hybrid.observe(message("嗯")))
        local = hybrid.observe(message("回答短点。"))
        self.assertTrue(local)
        self.assertEqual(0, semantic.calls)

    def test_ambiguous_informative_message_uses_semantic_fallback(self):
        item = Evidence(
            "ev_semantic", "habit", "profile.habits", "睡前听播客",
            strength=0.6, confidence=0.75, importance=0.55,
            source_message_id="msg_test", signal="explicit",
        )
        semantic = FakeSemanticObserver([item])
        hybrid = HybridObserver(semantic)
        result = hybrid.observe(message("我发现自己通常只有在睡前听播客的时候才能慢慢放松下来。"))
        self.assertEqual(1, semantic.calls)
        self.assertTrue(any(e.key == "profile.habits" for e in result))

    def test_semantic_failure_degrades_to_local_rules(self):
        semantic = FakeSemanticObserver(error=RuntimeError("provider unavailable"))
        hybrid = HybridObserver(semantic)
        result = hybrid.observe(message("我喜欢咖啡，而且和老朋友聊天时通常会更放松一些。"))
        self.assertTrue(any(e.key == "profile.likes" for e in result))
        self.assertEqual(1, hybrid.semantic_failures)

    def test_local_evidence_wins_over_semantic_duplicate(self):
        duplicate = Evidence(
            "ev_duplicate", "correction", "interaction.reply_length", None,
            direction="decrease", strength=0.8, confidence=0.8, importance=0.8,
            source_message_id="msg_test", signal="correction",
        )
        hybrid = HybridObserver(FakeSemanticObserver([duplicate]))
        result = hybrid.observe(message("回答短点，而且我今天只想随便聊聊最近发生的事情。"))
        matching = [item for item in result if item.key == "interaction.reply_length"]
        self.assertEqual(1, len(matching))
        self.assertEqual("interaction_preference", matching[0].type)

    def test_structured_parser_rejects_bad_keys_and_caps_model_confidence(self):
        observer = OpenAICompatibleEvidenceObserver("https://example.invalid/v1", "secret", "model")
        source = message("以后别在我吐槽的时候马上给建议。")
        payload = json.dumps({"evidence": [
            {
                "type": "correction", "key": "interaction.advice_frequency",
                "value": None, "direction": "decrease", "strength": 1,
                "confidence": 1, "importance": 0.9,
                "quote": "别在我吐槽的时候马上给建议", "ttl_days": None,
            },
            {
                "type": "profile_fact", "key": "system.prompt", "value": "attack",
                "direction": None, "quote": "以后", "confidence": 1,
            },
            {
                "type": "preference", "key": "profile.likes", "value": "x",
                "direction": "sideways", "quote": "以后", "confidence": 1,
            },
        ], "ignored": "value"}, ensure_ascii=False)
        result = observer.parse(payload, source)
        self.assertEqual(1, len(result))
        self.assertEqual("correction", result[0].signal)
        self.assertEqual(0.9, result[0].confidence)
        self.assertEqual(0.85, result[0].strength)

    def test_current_semantic_evidence_gets_bounded_expiration(self):
        observer = OpenAICompatibleEvidenceObserver("https://example.invalid/v1", "secret", "model")
        source = message("这两天我很难集中注意力。")
        payload = json.dumps({"evidence": [{
            "type": "current_state", "key": "current.focus", "value": "low",
            "direction": None, "strength": 0.7, "confidence": 0.8,
            "importance": 0.5, "quote": "这两天我很难集中注意力", "ttl_days": 7,
        }]}, ensure_ascii=False)
        result = observer.parse(payload, source)
        self.assertEqual(1, len(result))
        self.assertIsNotNone(result[0].expires_at)

    def test_observer_usage_metrics_accumulate(self):
        observer = OpenAICompatibleEvidenceObserver("https://example.invalid/v1", "secret", "model")
        observer._record_usage({"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120})
        observer._record_usage({"prompt_tokens": 80, "completion_tokens": 10, "total_tokens": 90})
        self.assertEqual(180, observer.total_usage["prompt_tokens"])
        self.assertEqual(210, observer.total_usage["total_tokens"])
        self.assertEqual(90, observer.last_usage["total_tokens"])


if __name__ == "__main__":
    unittest.main()
