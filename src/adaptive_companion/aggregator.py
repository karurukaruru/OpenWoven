from __future__ import annotations

import json
import sqlite3
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .models import DEFAULT_INTERACTION, INTERACTION_KEYS, utc_now
from .storage import SQLiteStore


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


@dataclass(slots=True)
class AggregationConfig:
    weak_rate: float = 0.025
    explicit_rate: float = 0.11
    correction_rate: float = 0.36


class EvidenceAggregator:
    """Rebuilds beliefs deterministically from ordered evidence in one transaction."""

    def __init__(self, store: SQLiteStore, config: AggregationConfig | None = None,
                 interaction_defaults: dict[str, float] | None = None):
        self.store = store
        self.config = config or AggregationConfig()
        self.interaction_defaults = {**DEFAULT_INTERACTION, **(interaction_defaults or {})}

    def aggregate(
        self, force_keys: set[str] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        # Deletion can rebuild AUL inside its own transaction: no crash window
        # with deleted raw inputs but stale sensitive beliefs still committed.
        with (nullcontext(connection) if connection is not None else self.store.connection()) as conn:
            if connection is None:
                conn.execute("BEGIN IMMEDIATE")
            state_row = conn.execute(
                "SELECT data_json,version FROM aul_state WHERE singleton=1"
            ).fetchone()
            old = json.loads(state_row["data_json"])
            old_version = int(state_row["version"])
            affected = {
                row["key"] for row in conn.execute(
                    "SELECT DISTINCT key FROM evidence WHERE applied=0"
                ).fetchall()
            }
            affected.update(force_keys or set())
            # Expiration is evaluated even when the next message has no evidence.
            for field, value in old.get("current", {}).items():
                values = value if isinstance(value, list) else [value]
                if any(isinstance(item, dict) and self._expired(item.get("expires_at")) for item in values):
                    affected.add(f"current.{field}")

            rows = []
            if affected:
                placeholders = ",".join("?" for _ in affected)
                rows = conn.execute(
                    f"""SELECT e.*, m.timestamp AS source_time, m.rowid AS source_order
                    FROM evidence e JOIN messages m ON m.id=e.source_message_id
                    WHERE e.key IN ({placeholders})
                    ORDER BY m.timestamp, m.rowid, e.rowid""",
                    tuple(sorted(affected)),
                ).fetchall()
            user_count = conn.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE role='user'"
            ).fetchone()["n"]

            new = self._base_state(old, affected)
            new["relationship"]["interaction_count"] = int(user_count)
            new["relationship"]["familiarity"] = _clamp(min(1.0, user_count / 100.0))

            latest_sources: dict[str, tuple[str, str, float]] = {}
            for row in rows:
                value = json.loads(row["value_json"]) if row["value_json"] is not None else None
                key = row["key"]
                if key.startswith("interaction."):
                    pref_key = key.split(".", 1)[1]
                    if pref_key in INTERACTION_KEYS:
                        pref = new["interaction"][pref_key]
                        if row["signal"] == "baseline" and isinstance(value, (int, float)):
                            # Onboarding is an explicit starting point, not a weak
                            # directional observation. Later evidence is replayed on top.
                            pref["value"] = _clamp(float(value))
                        else:
                            rate = self._learning_rate(row["signal"], row["strength"])
                            target = 1.0 if row["direction"] == "increase" else 0.0
                            pref["value"] = _clamp(pref["value"] + (target - pref["value"]) * rate)
                        pref["evidence_count"] += 1
                        certainty_gain = row["confidence"] * (0.32 if row["signal"] == "correction" else 0.18)
                        pref["confidence"] = _clamp(1 - (1 - pref["confidence"]) * (1 - certainty_gain))
                        pref["last_updated"] = row["source_time"]
                        latest_sources[key] = (row["id"], row["source_message_id"], row["confidence"])
                elif key.startswith("profile."):
                    field = key.split(".", 1)[1]
                    if field in {"interests", "likes", "dislikes", "habits", "goals"}:
                        if value and not any(x.get("value") == value for x in new["profile"][field]):
                            new["profile"][field].append(self._belief(value, row))
                    elif field in new["profile"]:
                        current = new["profile"].get(field)
                        explicit_update = row["signal"] in {"explicit", "correction", "baseline"} and row["confidence"] >= 0.6
                        if not current or explicit_update or row["confidence"] >= current.get("confidence", 0):
                            new["profile"][field] = self._belief(value, row)
                    latest_sources[key] = (row["id"], row["source_message_id"], row["confidence"])
                elif key.startswith("current.") and not self._expired(row["expires_at"]):
                    field = key.split(".", 1)[1]
                    belief = self._belief(value, row, row["expires_at"])
                    if field in {"active_topics", "recent_events", "unfinished_topics"}:
                        if field not in new["current"]:
                            new["current"][field] = []
                        new["current"][field].append(belief)
                        new["current"][field] = new["current"][field][-10:]
                    elif row["type"] == "state_change" and value is None:
                        new["current"][field] = None
                    else:
                        new["current"][field] = belief
                    latest_sources[key] = (row["id"], row["source_message_id"], row["confidence"])
                elif key.startswith("relationship."):
                    field = key.split(".", 1)[1]
                    if field in {"common_topics", "shared_history"} and value:
                        if not any(self._value_of(item) == value for item in new["relationship"][field]):
                            new["relationship"][field].append(self._belief(value, row))
                            new["relationship"][field] = new["relationship"][field][-12:]
                    latest_sources[key] = (row["id"], row["source_message_id"], row["confidence"])

            changed = self._diff(old, new)
            if changed:
                version = old_version + 1
                now = utc_now()
                new["version"] = version
                new["updated_at"] = now
                conn.execute(
                    "UPDATE aul_state SET data_json=?,version=?,updated_at=? WHERE singleton=1 AND version=?",
                    (json.dumps(new, ensure_ascii=False), version, now, old_version),
                )
                for field, old_value, new_value in changed:
                    source = latest_sources.get(field, (None, None, 0.0))
                    conn.execute(
                        """INSERT INTO audit_log
                        (created_at,field,old_value_json,new_value_json,reason,evidence_id,
                         source_message_id,confidence,aul_version) VALUES(?,?,?,?,?,?,?,?,?)""",
                        (now, field, json.dumps(old_value, ensure_ascii=False),
                         json.dumps(new_value, ensure_ascii=False),
                         self._reason(field, source[0]), source[0], source[1], source[2], version),
                    )
            conn.execute("UPDATE evidence SET applied=1 WHERE applied=0")
            if connection is None:
                conn.commit()
            return new if changed else self.store.get_aul()

    def _base_state(self, previous: dict[str, Any], affected: set[str]) -> dict[str, Any]:
        # Only affected belief keys are replayed. This keeps completion-order
        # independence without scanning unrelated lifetime evidence each turn.
        result = deepcopy(previous)
        for full_key in affected:
            section, _, key = full_key.partition(".")
            if section == "interaction" and key in DEFAULT_INTERACTION:
                result["interaction"][key] = {
                    "value": self.interaction_defaults[key], "confidence": 0.0,
                    "evidence_count": 0, "last_updated": None,
                }
            elif section == "profile" and key in result["profile"]:
                result["profile"][key] = [] if key in {
                    "interests", "likes", "dislikes", "habits", "goals"
                } else None
            elif section == "current":
                result["current"][key] = [] if key in {
                    "active_topics", "recent_events", "unfinished_topics"
                } else None
            elif section == "relationship" and key in {"common_topics", "shared_history"}:
                result["relationship"][key] = []
        return result

    @staticmethod
    def _value_of(item: Any) -> Any:
        return item.get("value") if isinstance(item, dict) else item

    def _learning_rate(self, signal: str, strength: float) -> float:
        base = {
            "inferred": self.config.weak_rate,
            "implicit": self.config.weak_rate,
            "explicit": self.config.explicit_rate,
            "correction": self.config.correction_rate,
        }.get(signal, self.config.weak_rate)
        return min(0.45, base * max(0.2, float(strength)))

    @staticmethod
    def _belief(value: Any, row: Any, expires_at: str | None = None) -> dict[str, Any]:
        result = {
            "value": value,
            "confidence": round(float(row["confidence"]), 4),
            "evidence_ids": [row["id"]],
            "last_updated": row["source_time"],
        }
        if expires_at:
            result["expires_at"] = expires_at
        return result

    @staticmethod
    def _expired(value: str | None) -> bool:
        if not value:
            return False
        return datetime.fromisoformat(value) <= datetime.now(UTC)

    @staticmethod
    def _diff(old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, Any, Any]]:
        changes: list[tuple[str, Any, Any]] = []
        for key in INTERACTION_KEYS:
            # Confidence/count/time are durable belief state too. A baseline at
            # the default value must not silently discard its supporting evidence.
            old_value = old["interaction"][key]
            new_value = new["interaction"][key]
            if old_value != new_value:
                changes.append((f"interaction.{key}", old_value, new_value))
        for section in ("profile", "current", "relationship"):
            for key, value in new[section].items():
                if old.get(section, {}).get(key) != value:
                    changes.append((f"{section}.{key}", old.get(section, {}).get(key), value))
        return changes

    @staticmethod
    def _reason(field: str, evidence_id: str | None) -> str:
        if field == "relationship.interaction_count":
            return "Observed another user interaction"
        if field == "relationship.familiarity":
            return "Familiarity derived from interaction count"
        if field.startswith('interaction.') and evidence_id is None:
            return "Preference restored from configured starting style; no user evidence"
        return f"Belief recomputed from weighted evidence; latest relevant evidence: {evidence_id}"
