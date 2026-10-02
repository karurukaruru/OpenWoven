from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from .aggregator import EvidenceAggregator
from .models import Evidence
from .storage import SQLiteStore


FEEDBACK_MAP: dict[str, list[tuple[str, str, str | None, float]]] = {
    "too_long": [("correction", "interaction.reply_length", "decrease", 1.0)],
    "too_short": [("correction", "interaction.reply_length", "increase", 1.0)],
    "too_many_questions": [("correction", "interaction.question_frequency", "decrease", 1.0)],
    "too_cold": [
        ("correction", "interaction.warmth", "increase", 0.9),
        ("correction", "interaction.empathy", "increase", 0.75),
    ],
    "too_verbose": [
        ("correction", "interaction.reply_length", "decrease", 0.9),
        ("correction", "interaction.directness", "increase", 0.75),
    ],
    "too_serious": [("correction", "interaction.humor", "increase", 0.8)],
    "too_playful": [
        ("correction", "interaction.humor", "decrease", 0.85),
        ("correction", "interaction.teasing", "decrease", 0.9),
    ],
    "too_much_initiative": [("correction", "interaction.initiative", "decrease", 0.9)],
    "too_little_initiative": [("correction", "interaction.initiative", "increase", 0.9)],
}


class FeedbackService:
    def __init__(self, store: SQLiteStore, aggregator: EvidenceAggregator):
        self.store = store
        self.aggregator = aggregator

    def submit(self, message_id: str, kind: str, value: Any = None) -> dict[str, Any]:
        if not self.store.get_message(message_id):
            raise ValueError("feedback target message does not exist")
        normalized = kind.strip().lower()
        existing = self.store.find_feedback(message_id, normalized)
        if existing:
            return {
                "feedback_id": existing, "evidence_ids": [],
                "aul": self.store.get_aul(), "duplicate": True,
            }
        feedback_id = self.store.save_feedback(message_id, normalized, value)
        evidence = self._evidence(message_id, normalized)
        self.store.save_evidence(evidence)
        state = self.aggregator.aggregate()
        self.store.set_metadata("feedback_last_at", datetime.now(UTC).isoformat())
        self.store.set_metadata("feedback_dismissals", "0")
        return {"feedback_id": feedback_id, "evidence_ids": [item.id for item in evidence], "aul": state}

    def complete_periodic(self) -> None:
        self.store.set_metadata("feedback_last_at", datetime.now(UTC).isoformat())
        self.store.set_metadata("feedback_dismissals", "0")

    def dismiss_periodic(self) -> None:
        count = int(self.store.get_metadata("feedback_dismissals") or "0") + 1
        self.store.set_metadata("feedback_dismissals", str(count))
        self.store.set_metadata("feedback_last_at", datetime.now(UTC).isoformat())

    def should_request_periodic(self, minimum_interactions: int = 20, minimum_days: int = 7) -> bool:
        interactions = self.store.count_messages(role="user")
        if interactions < minimum_interactions:
            return False
        dismissals = int(self.store.get_metadata("feedback_dismissals") or "0")
        wait_days = minimum_days + min(21, dismissals * 3)
        last = self.store.get_metadata("feedback_last_at")
        return not last or datetime.fromisoformat(last) <= datetime.now(UTC) - timedelta(days=wait_days)

    @staticmethod
    def _evidence(message_id: str, kind: str) -> list[Evidence]:
        result = []
        for type_, key, direction, strength in FEEDBACK_MAP.get(kind, []):
            result.append(Evidence(
                id=f"ev_{uuid.uuid4().hex}", type=type_, key=key,
                direction=direction, strength=strength, confidence=0.995,
                importance=0.95, source_message_id=message_id, signal="correction",
            ))
        if kind in {"good", "thumb_up", "thumb_down"}:
            sentiment = "positive" if kind in {"good", "thumb_up"} else "negative"
            result.append(Evidence(
                id=f"ev_{uuid.uuid4().hex}", type="relationship_context",
                key="relationship.shared_history", value=f"{sentiment} message feedback",
                strength=0.7, confidence=0.99, importance=0.55,
                source_message_id=message_id, signal="explicit",
            ))
        return result
