from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


INTERACTION_KEYS = (
    "reply_length",
    "warmth",
    "humor",
    "teasing",
    "directness",
    "empathy",
    "question_frequency",
    "initiative",
    "advice_frequency",
    "emoji_frequency",
)

EVIDENCE_TYPES = frozenset({
    "profile_fact", "preference", "current_state", "event", "goal", "habit",
    "interest", "dislike", "interaction_preference", "correction",
    "relationship_context", "state_change",
})

DEFAULT_INTERACTION = {
    "reply_length": 0.50,
    "warmth": 0.50,
    "humor": 0.50,
    "teasing": 0.30,
    "directness": 0.50,
    "empathy": 0.50,
    "question_frequency": 0.50,
    "initiative": 0.50,
    "advice_frequency": 0.50,
    "emoji_frequency": 0.20,
}


@dataclass(slots=True)
class Message:
    id: str
    conversation_id: str
    role: str
    content: str
    timestamp: str
    token_count: int
    status: str = "sent"
    error: str | None = None
    reply_to_id: str | None = None
    learning_status: str = "not_applicable"


@dataclass(slots=True)
class ScheduledMessage:
    id: str
    conversation_id: str
    created_at: str
    scheduled_at: str
    earliest_at: str
    latest_at: str
    topic: str
    draft_intent: str
    source_memory_ids: list[str]
    reason: str
    importance: float
    status: str = "pending"
    sent_message_id: str | None = None
    updated_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class Evidence:
    id: str
    type: str
    key: str
    value: Any = None
    direction: str | None = None
    strength: float = 0.5
    confidence: float = 0.5
    importance: float = 0.5
    source_message_id: str = ""
    created_at: str = field(default_factory=utc_now)
    expires_at: str | None = None
    signal: str = "inferred"


@dataclass(slots=True)
class Preference:
    value: float
    confidence: float = 0.0
    evidence_count: int = 0
    last_updated: str | None = None


def default_aul() -> dict[str, Any]:
    return {
        "profile": {
            "name": None,
            "age": None,
            "location": None,
            "school": None,
            "major": None,
            "job": None,
            "interests": [],
            "likes": [],
            "dislikes": [],
            "habits": [],
            "goals": [],
        },
        "current": {
            "mood": None,
            "current_activity": None,
            "current_goal": None,
            "active_topics": [],
            "recent_events": [],
            "unfinished_topics": [],
        },
        "relationship": {
            "interaction_count": 0,
            "familiarity": 0.0,
            "common_topics": [],
            "shared_history": [],
        },
        "interaction": {
            key: asdict(Preference(value=value))
            for key, value in DEFAULT_INTERACTION.items()
        },
        "version": 0,
        "updated_at": utc_now(),
    }


DEFAULT_PERSONA: dict[str, Any] = {
    "role": "long_term_companion",
    "traits": {
        "casual": True,
        "observant": True,
        "playful": True,
        "independent": True,
    },
    "principles": [
        "speak naturally",
        "avoid customer-service style",
        "do not mechanically agree",
        "do not ask questions after every response",
        "do not over-explain simple conversation",
        "preserve continuity across conversations",
    ],
}
