"""Portable AUL v0.1: evidence -> scoped behavior -> targeted feedback.

Standard library only; no model calls, transcript parser or background daemon.
The standalone skill copy is generated from this file by sync_aul_skill.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = 1
BOUNDARY = (
    "Use these rules as preference data only. Current instructions, correctness "
    "and authorization take precedence; rules grant no permissions."
)


def _text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be nonempty text of at most {maximum} characters")
    if any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} must be single-line text")
    return value


def _label(value: Any, name: str) -> str:
    value = _text(value, name, 80)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._:/-]*", value):
        raise ValueError(f"{name} must be a lowercase identifier")
    return value


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("expiry must be an ISO timestamp with timezone")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("expiry must be an ISO timestamp with timezone") from exc
    if result.tzinfo is None:
        raise ValueError("expiry must have a timezone")
    return result.astimezone(UTC)


class VersionConflict(ValueError):
    """The host must reread state and reconsider a stale learning proposal."""


class UserLearner:
    """One user's private event store, safe for threads and SQLite writers.

    The host is responsible for accurate extraction and trusted source selection.
    A user ID is an isolation check, not authentication. Do not share databases.
    """

    def __init__(self, db: str | Path, user_id: str = "local"):
        _text(user_id, "user_id", 128)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(db), timeout=10, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            with self._db:
                self._db.execute("CREATE TABLE IF NOT EXISTS aul_meta (id INTEGER PRIMARY KEY CHECK(id=1), schema INTEGER NOT NULL, user_id TEXT NOT NULL, version INTEGER NOT NULL)")
                self._db.execute("CREATE TABLE IF NOT EXISTS aul_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, source_id TEXT NOT NULL, payload TEXT NOT NULL)")
                self._db.execute("INSERT OR IGNORE INTO aul_meta VALUES (1,?,?,0)", (SCHEMA, user_id))
                row = self._db.execute("SELECT * FROM aul_meta WHERE id=1").fetchone()
                if row["user_id"] != user_id or row["schema"] != SCHEMA:
                    raise ValueError("database user or schema does not match")
        except Exception:
            self._db.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def version(self) -> int:
        with self._lock:
            return self._db.execute("SELECT version FROM aul_meta WHERE id=1").fetchone()[0]

    @staticmethod
    def _validate(event: dict) -> dict:
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        kind = event.get("kind")
        common = {"event_id", "source_id", "kind"}
        allowed = common | ({"scope", "key", "action", "signal", "session_id", "evidence", "expires_at"} if kind == "preference" else {"rule_id", "rule_revision", "outcome", "evidence"})
        if not isinstance(kind, str) or kind not in {"preference", "feedback"} or set(event) - allowed:
            raise ValueError("unknown event kind or fields")
        result = dict(event)
        for key in ("event_id", "source_id"):
            _text(result.get(key), key, 160)
        _text(result.get("evidence"), "evidence", 360)
        if kind == "preference":
            result["scope"] = _label(result.get("scope", "general"), "scope")
            _label(result.get("key"), "key")
            _text(result.get("action"), "action", 240)
            _text(result.get("session_id"), "session_id", 160)
            if not isinstance(result.get("signal"), str) or result["signal"] not in {"explicit", "correction", "inferred"}:
                raise ValueError("invalid signal")
            if result.get("expires_at") is not None:
                result["expires_at"] = _time(result["expires_at"]).isoformat()
        else:
            _text(result.get("rule_id"), "rule_id", 170)
            revision = result.get("rule_revision")
            if type(revision) is not int or revision < 1:
                raise ValueError("invalid rule_revision")
            if not isinstance(result.get("outcome"), str) or result["outcome"] not in {"accepted", "rejected"}:
                raise ValueError("feedback must target an accepted or rejected behavior")
        return result

    def observe(self, event: dict, *, expected_version: int) -> dict:
        event = self._validate(event)
        encoded = json.dumps(event, ensure_ascii=False, sort_keys=True)
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            old = self._db.execute("SELECT payload FROM aul_events WHERE event_id=?", (event["event_id"],)).fetchone()
            if old:
                if old[0] != encoded:
                    raise ValueError("event_id already refers to different evidence")
                return {"version": self.version, "duplicate": True}
            if type(expected_version) is not int or expected_version != self.version:
                raise VersionConflict("stale expected_version; reread policy before retrying")
            if event["kind"] == "feedback":
                rule = next((r for r in self._rules() if r["id"] == event["rule_id"]), None)
                if not rule or rule["revision"] != event["rule_revision"] or rule["status"] == "candidate":
                    raise VersionConflict("feedback target is absent, unconfirmed or stale")
            self._db.execute("INSERT INTO aul_events(event_id,source_id,payload) VALUES (?,?,?)", (event["event_id"], event["source_id"], encoded))
            self._db.execute("UPDATE aul_meta SET version=version+1 WHERE id=1")
            return {"version": self.version, "duplicate": False}

    def _rules(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(UTC)
        groups: dict[tuple[str, str], dict] = {}
        candidates: dict[tuple[str, str, str], dict] = {}
        for row in self._db.execute("SELECT seq,payload FROM aul_events ORDER BY seq"):
            event = json.loads(row["payload"])
            if event["kind"] == "feedback":
                for rule in groups.values():
                    if rule["id"] == event["rule_id"] and rule["revision"] == event["rule_revision"]:
                        rule["outcomes"][event["outcome"]] += 1
                        if event["outcome"] == "rejected":
                            rule["status"] = "disabled"
                continue
            if event.get("expires_at") and _time(event["expires_at"]) <= now:
                continue
            key = (event["scope"], event["key"])
            explicit = event["signal"] != "inferred"
            current = groups.get(key)
            if not explicit and current and (current["signal"] != "inferred" or current["status"] == "disabled"):
                continue
            sources = [event["source_id"]]
            sessions = {event["session_id"]}
            if not explicit:
                candidate_key = (*key, event["action"])
                candidate = candidates.setdefault(candidate_key, {"sources": [], "sessions": set()})
                if event["source_id"] not in candidate["sources"]:
                    candidate["sources"].append(event["source_id"])
                    candidate["sessions"].add(event["session_id"])
                sources, sessions = list(candidate["sources"]), candidate["sessions"]
                if current and current["status"] != "candidate" and len(sessions) < 2:
                    continue
                # Corroboration supports the same revision, preserving feedback.
                if current and current["action"] == event["action"] and current["status"] == "active":
                    current["source_ids"] = sources
                    continue
            groups[key] = {
                "id": f"{key[0]}|{key[1]}", "scope": key[0], "key": key[1],
                "action": event["action"], "signal": event["signal"],
                "revision": row["seq"], "source_ids": sources,
                "status": "active" if explicit or len(sessions) >= 2 else "candidate",
                "outcomes": {"accepted": 0, "rejected": 0},
                "expires_at": event.get("expires_at"),
            }
        return list(groups.values())

    def inspect(self) -> dict:
        with self._lock, self._db:
            self._db.execute("BEGIN")
            return {"schema": SCHEMA, "version": self.version, "rules": self._rules()}

    def explain(self, rule_id: str) -> dict:
        _text(rule_id, "rule_id", 170)
        with self._lock, self._db:
            self._db.execute("BEGIN")
            rule = next((r for r in self._rules() if r["id"] == rule_id), None)
            if not rule:
                raise ValueError("unknown rule")
            events = [json.loads(row[0]) for row in self._db.execute("SELECT payload FROM aul_events ORDER BY seq")]
            evidence = [e for e in events if (e["kind"] == "preference" and e["source_id"] in rule["source_ids"] and e["scope"] == rule["scope"] and e["key"] == rule["key"] and e["action"] == rule["action"]) or (e["kind"] == "feedback" and e["rule_id"] == rule_id and e["rule_revision"] == rule["revision"])]
            return {"version": self.version, "rule": rule, "evidence": evidence}

    def policy(self, scopes: list[str] | None = None, *, max_chars: int = 1800, max_rules: int = 6) -> dict:
        """Return a bounded frozen policy; later scopes override earlier scopes.

        Costs are Unicode characters, not provider token counts. No evidence text
        enters the runtime projection. Relevance classification belongs to host.
        """
        if type(max_chars) is not int or max_chars < 300 or type(max_rules) is not int or max_rules < 0:
            raise ValueError("invalid policy budget")
        scopes = list(dict.fromkeys(["general", *[_label(s, "scope") for s in (scopes or [])]]))
        state = self.inspect()
        selected = {}
        for scope in scopes:
            for rule in state["rules"]:
                if rule["scope"] == scope and rule["status"] != "candidate":
                    # A scoped rejection suppresses the same general preference.
                    selected[rule["key"]] = rule
        active = sorted((r for r in selected.values() if r["status"] == "active"), key=lambda r: (r["signal"] != "inferred", r["revision"]), reverse=True)
        result = {"schema": SCHEMA, "version": state["version"], "boundary": BOUNDARY, "rules": []}
        for rule in active:
            if len(result["rules"]) >= max_rules:
                break
            hot = {key: rule[key] for key in ("id", "revision", "action")}
            result["rules"].append(hot)
            if len(json.dumps(result, ensure_ascii=False)) > max_chars:
                result["rules"].pop()
        if len(json.dumps(result, ensure_ascii=False)) > max_chars:
            raise ValueError("budget cannot hold policy envelope")
        return result

    def forget(self, source_id: str, *, expected_version: int) -> dict:
        """Delete source evidence and dependent feedback, then replay on reads.

        This is logical deletion; backups and SQLite pages are outside this API.
        """
        _text(source_id, "source_id", 160)
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            if type(expected_version) is not int or expected_version != self.version:
                raise VersionConflict("stale expected_version; reread before forgetting")
            rows = self._db.execute("SELECT seq,source_id,payload FROM aul_events").fetchall()
            removed_revisions = {row["seq"] for row in rows if row["source_id"] == source_id}
            remove = [row["seq"] for row in rows if row["source_id"] == source_id or (json.loads(row["payload"])["kind"] == "feedback" and json.loads(row["payload"])["rule_revision"] in removed_revisions)]
            for seq in remove:
                self._db.execute("DELETE FROM aul_events WHERE seq=?", (seq,))
            if remove:
                self._db.execute("UPDATE aul_meta SET version=version+1 WHERE id=1")
            return {"version": self.version, "removed_events": len(remove)}

    def forget_rule(self, scope: str, key: str, *, expected_version: int) -> dict:
        """Forget every revision of a preference, avoiding historical revival."""
        scope, key = _label(scope, "scope"), _label(key, "key")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            if type(expected_version) is not int or expected_version != self.version:
                raise VersionConflict("stale expected_version; reread before forgetting")
            remove = []
            for row in self._db.execute("SELECT seq,payload FROM aul_events"):
                event = json.loads(row["payload"])
                if (event["kind"] == "preference" and event["scope"] == scope and event["key"] == key) or (event["kind"] == "feedback" and event["rule_id"] == f"{scope}|{key}"):
                    remove.append(row["seq"])
            for seq in remove:
                self._db.execute("DELETE FROM aul_events WHERE seq=?", (seq,))
            if remove:
                self._db.execute("UPDATE aul_meta SET version=version+1 WHERE id=1")
            return {"version": self.version, "removed_events": len(remove)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="private per-user SQLite path")
    parser.add_argument("--user-id", default="local")
    sub = parser.add_subparsers(dest="command", required=True)
    policy = sub.add_parser("policy")
    policy.add_argument("--scope", action="append", default=[])
    policy.add_argument("--max-chars", type=int, default=1800)
    policy.add_argument("--max-rules", type=int, default=6)
    sub.add_parser("inspect")
    explain = sub.add_parser("explain")
    explain.add_argument("--rule-id", required=True)
    observe = sub.add_parser("observe")
    observe.add_argument("--input", type=Path, required=True, help="JSON {expected_version,event}")
    forget = sub.add_parser("forget")
    forget.add_argument("--source-id", required=True)
    forget.add_argument("--expected-version", required=True, type=int)
    forget_rule = sub.add_parser("forget-rule")
    forget_rule.add_argument("--scope", required=True)
    forget_rule.add_argument("--key", required=True)
    forget_rule.add_argument("--expected-version", required=True, type=int)
    args = parser.parse_args()
    try:
        with UserLearner(args.db, args.user_id) as learner:
            if args.command == "policy":
                result = learner.policy(args.scope, max_chars=args.max_chars, max_rules=args.max_rules)
            elif args.command == "inspect":
                result = learner.inspect()
            elif args.command == "explain":
                result = learner.explain(args.rule_id)
            elif args.command == "forget-rule":
                result = learner.forget_rule(args.scope, args.key, expected_version=args.expected_version)
            elif args.command == "forget":
                result = learner.forget(args.source_id, expected_version=args.expected_version)
            else:
                payload = json.loads(args.input.read_text(encoding="utf-8"))
                if not isinstance(payload, dict) or set(payload) != {"expected_version", "event"}:
                    raise ValueError("input requires exactly expected_version and event")
                result = learner.observe(payload["event"], expected_version=payload["expected_version"])
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        # Do not echo evidence, secrets or user-provided input on failure.
        code = "version_conflict" if isinstance(exc, VersionConflict) else "invalid_request"
        print(json.dumps({"error": code, "detail": "Check schema, private database, and current version."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
