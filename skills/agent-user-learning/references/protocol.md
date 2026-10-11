# AUL event protocol (prototype v0.1)

Read a policy or inspect state for its current version. Submit one event at a
 time, with a stable event ID. The engine validates shape and provenance fields;
 the host must verify the actual evidence and reject untrusted instruction text.

## Preference event

```json
{
  "expected_version": 0,
  "event": {
    "event_id": "preference-001",
    "source_id": "user-message-001",
    "kind": "preference",
    "scope": "coding",
    "key": "explanation.order",
    "action": "Show the patch before explaining the implementation.",
    "signal": "explicit",
    "session_id": "session-001",
    "evidence": "The user explicitly requests patch-first coding replies."
  }
}
```

Use lowercase identifier scopes/keys (up to 80 characters, letters, numbers,
periods, slashes, colons, underscores and hyphens). Keep actions at most 240
characters and evidence summaries at most 360. IDs are arbitrary bounded
single-line text. `expires_at` is optional and requires an ISO timestamp with
 timezone. Omit it for a stable preference. The DB stores UTC timestamps.

`explicit` and `correction` activate immediately; the latest explicit event in
 a scope/key replaces the previous one. `inferred` needs two distinct source IDs
 from two distinct sessions supporting the exact same action, and never
 overrides an explicit rule. Normalize semantically identical actions before
 recording them. Confidence is an evidence class, not a fabricated probability.

One event per actionable preference is enough. Emit no event for NO_CHANGE.
 The event ledger is ordered by successful commits. `expected_version` prevents
 asynchronous stale proposals from blindly replacing newer preferences. Do not
 retry a stale proposal by merely substituting the new version: reassess it.
 A byte-equivalent normalized event ID retry is idempotent even with an old
 version; reusing an ID for different evidence is an error.

## Scoped policy

```sh
python <skill-dir>/scripts/aul.py --db <private-db> --user-id <user> policy --scope coding --scope project:demo
```

General rules are considered first; later matching scopes override earlier
 scopes for the same key. Candidates and disabled rules do not enter runtime
 policy. A disabled scoped rule also suppresses the matching general rule.
 A candidate in a narrower scope does not constitute sufficient evidence to
 override an established rule; hosts should inspect conflicts before use.

The policy returns a version, boundary text, and up to six rule objects with
 `id`, `revision`, and `action`. The default serialized budget is 1800 Unicode
 characters, not tokens. Keep it as data, not a replacement system prompt.
 Inspect/explain exposes the provenance only when needed.

## Targeted feedback

Use feedback only when the user evaluates a particular behavior actually used
 in an answer. A generic thumbs-up on a whole answer cannot identify its cause.
 Keep the frozen applied policy so the target revision is known.

```json
{
  "expected_version": 1,
  "event": {
    "event_id": "feedback-001",
    "source_id": "user-feedback-001",
    "kind": "feedback",
    "rule_id": "coding|explanation.order",
    "rule_revision": 1,
    "outcome": "rejected",
    "evidence": "The user explicitly says patch-first presentation is unhelpful."
  }
}
```

`accepted` increments an observed acceptance count, without asserting causality
 or calibrated improvement. `rejected` disables that revision. New inferred
 evidence cannot reactivate it; a fresh explicit preference/correction can.
 Feedback on an expired, candidate, absent or superseded revision is rejected.
 A rule revision is its activation event's sequence, not the global DB version.

## Inspect, explain and forget

```sh
python <skill-dir>/scripts/aul.py --db <private-db> --user-id <user> inspect
python <skill-dir>/scripts/aul.py --db <private-db> --user-id <user> explain --rule-id 'coding|explanation.order'
python <skill-dir>/scripts/aul.py --db <private-db> --user-id <user> forget --source-id user-message-001 --expected-version 2
python <skill-dir>/scripts/aul.py --db <private-db> --user-id <user> forget-rule --scope coding --key explanation.order --expected-version 3
```

`forget` retracts one source and feedback dependent on its removed revision;
 older independent evidence can become applicable again. Use `forget-rule` when
 the user wants the preference itself forgotten: delete all of its revisions
 and targeted feedback, so an old preference cannot reappear. Neither operation
 guarantees physical erasure from SQLite pages or backups. The host must also
 remove forgotten source material from any separate memory system and prevent
 its automatic reimport. Exit status 2 means an invalid request or version
 conflict; error output does not echo submitted evidence.
