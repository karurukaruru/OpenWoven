# Integrate AUL into an agent host

## Skill-based agents

Copy the entire `agent-user-learning` folder into the host's supported skill
 location, including scripts and references. Keep its name unchanged. Python
 3.11+ is required for the executable helper; no API key or external package is
 required. Restart or refresh skill discovery as the host requires.

Bind a private persistent DB path and user ID in host instructions. On a relevant
 task, load the skill and read the scoped policy before acting; after the answer,
 emit only evidence-backed changes. The skill is not an always-on hook or an
 automatic cross-agent synchronization service. Verify invocation with a known
 explicit correction and check the next task uses the revised policy.

## Product or custom agent

Use `openwoven.user_learning.UserLearner` from the source-installed OpenWoven
 package, or import the standalone `scripts/aul.py` module by file path. Use a
 separate database per authenticated user; do not treat the user ID as auth.

```python
from openwoven.user_learning import UserLearner

with UserLearner(private_db, user_id=authenticated_user_id) as learner:
    frozen = learner.policy(["coding", "project:demo"])
    # Host: provide frozen as bounded preference data to the acting model.
    # Host: fulfill the user's current request and retain the applied revisions.
    # Host: extract validated preference events from the user's own statements.
    # Host: serialize post-turn observe(event, expected_version=frozen["version"]).
```

Separate four responsibilities:

1. **Actor**: read a small frozen policy, perform the task, record which rules
   actually influenced the response. Never confuse retrieval with compliance.
2. **Observer**: examine recent trusted user corrections. Output NO_CHANGE or
   one minimal protocol event. Extraction can be done by the host LLM or by
   deterministic UI feedback. The helper itself does not understand prose.
3. **Updater**: validate and commit events with a version lease. Queue updates
   per user. On conflict, inspect current state and reconsider old evidence.
4. **Evaluator**: associate targeted user feedback with the applied rule and
   revision. Record outcomes; reject bad rules and replace them explicitly.

Add model extraction asynchronously only if the host has the infrastructure.
 Do not place an extra model call on the reply path by default. Scheduling,
 authentication, model billing and the factual memory store belong to the host.
 One DB can be shared by trusted local agents for one user, but each must supply
 contexts and obey version conflicts. For remote/multi-tenant systems, expose an
 authenticated service instead of distributing the database.

## OpenWoven boundary

The portable module follows the original AUL's asynchronous-learning,
 evidence and compact-projection design. It adds domain scopes and targeted
 behavior feedback. It is independent of the companion's `CompanionCore`,
 persona settings and SQLiteStore schema. This prototype does not migrate old
 profiles, replace the Android learner, synchronize chat memories, or train any
 model. Wire it explicitly when an app needs generic workflow learning.

## Evaluate actual usefulness

Use tasks from the user's normal work and compare baseline responses with
 policy-guided responses under the same model and task. Measure repeated
 corrections, user-rated appropriateness, task success and input cost. Include
 misleading evidence, conflicting contexts, new instructions and source
 deletion. Report participant/task counts and raw outcomes; do not announce
 percentage improvements from the deterministic offline demonstration.

Every policy read currently replays a local event ledger. Suitable for an early
 prototype; benchmark before large histories and consider a validated materialized
 projection later. Action/evidence text is free-form preference data: schema
 validation cannot prevent prompt injection or prove the extractor is correct.
