# AUL for general agents

AUL (AI User Learning) turns interaction evidence into a compact policy for how
an agent should help a particular user. It extends the idea used in OpenWoven
into coding, writing, study, tool use and conversation. The standalone prototype
is a skill plus a dependency-free Python engine. Model weights do not change.

**AUL learns the user's preferred way of working with an agent.** A factual
memory store can remember a project deadline; AUL can learn to show a small patch
before explaining it, or to explain a mathematical idea before a worked example.
The useful distinction is evidence producing a behavioral change, followed by
targeted feedback and correction. This is not evidence of human satisfaction or
a unique algorithm, and the prototype does not claim to outperform memory tools.

## Install the portable skill

Copy the entire [agent-user-learning](skills/agent-user-learning) folder into one
of the host's skill locations, retaining its scripts and references:

| Host | Project location | User location |
| --- | --- | --- |
| OpenCode | `.opencode/skills/agent-user-learning/` | `~/.config/opencode/skills/agent-user-learning/` |
| Claude Code | `.claude/skills/agent-user-learning/` | `~/.claude/skills/agent-user-learning/` |
| Codex | `.agents/skills/agent-user-learning/` | `~/.agents/skills/agent-user-learning/` |

Official references: [OpenCode](https://opencode.ai/docs/skills/),
[Claude Code](https://code.claude.com/docs/en/skills),
[Codex](https://developers.openai.com/codex/skills/).
Installation locations were checked on 2026-10-11. The executable helper needs
Python 3.11+. These are format/discovery targets, not claims of end-to-end
testing inside every host. Copying a folder does not install an automatic hook.

Bind a private database path and user ID in the agent's host instructions:

> Use agent-user-learning for recurring preferences and corrections. Keep its
> per-user database outside the repository. Read the policy for the current
> contexts before acting; current instructions override it. After responding,
> submit only evidence-backed changes and targeted feedback. Reassess version
> conflicts instead of blindly retrying old patches.

Invoke the skill by name if the host does not select it automatically. Verify
that a known correction changes the policy and influences the next answer.
Agents must actually read and follow the skill; it cannot alter every AI system
merely by being present in a GitHub repository.

## Run without an API key

From a source checkout:

```sh
python -m pip install -e .
python examples/user_learning_demo.py
```

The demo shows an empty policy, an explicit coding preference, its rejection,
a correction, and complete preference deletion. It does not generate answers
or measure user satisfaction. The skill's `scripts/aul.py` can also run directly
without installing OpenWoven or any dependencies.

## Embed in a product

```python
from openwoven.user_learning import UserLearner

with UserLearner(private_db, user_id=authenticated_user_id) as learner:
    policy = learner.policy(["coding", "project:example"])
    # Include policy as bounded preference data in the host's generation request.
    # Fulfill the current request, then extract and validate an event.
    learner.observe(event, expected_version=policy["version"])
```

The host supplies the `event`, selects context, authenticates users and performs
model extraction when needed. Keep a separate database per user. The engine
does not parse conversation prose, call APIs or schedule tasks. It stores
bounded evidence summaries and source IDs, not full transcripts. Do not pass
private source documents, credentials or health/personality guesses as rules.

Read [SKILL.md](skills/agent-user-learning/SKILL.md) for agent-facing procedure,
[protocol](skills/agent-user-learning/references/protocol.md) for JSON/CLI, and
[integration](skills/agent-user-learning/references/integration.md) for host
lifecycle and evaluation boundaries.

## What this version implements

- Explicit preferences and corrections; two-session confirmation for inference.
- Task/project scopes and compact policies with a character budget.
- Targeted acceptance/rejection attached to a specific rule revision.
- Provenance inspection, source retraction and full preference deletion.
- Idempotent events, SQLite transactions, version conflict checks and restart
  persistence. Different user IDs cannot open the same AUL database.

Current user instructions, correctness and permissions override stored policy.
The host must exclude malicious instructions and verify evidence: JSON schema
validation alone cannot establish trust. Deletion is logical and does not erase
backups or external memory. Replaying the event ledger on each read is an early
prototype implementation; large histories need performance measurement.

OpenWoven's current Android/chat learner remains a separate implementation.
This module neither migrates existing profiles nor silently replaces the
companion's learning loop. Both follow evidence -> policy -> later interaction;
the portable engine adds general workflow rules and direct behavior evaluation.

## Development and evidence

```sh
python scripts/sync_aul_skill.py --check
python -m unittest tests.test_user_learning -v
```

`src/openwoven/user_learning.py` is the SDK source; the sync script generates
the standalone runtime. The regression suite checks offline policy transitions,
scope conflicts, expiry, provenance, forgetting, stale writes, concurrency and
CLI portability. It cannot show the real model obeys policy or that users feel
better. A useful next evaluation compares the same real tasks/model with and
without AUL, recording repeated corrections, appropriateness and task completion.

Keep the first public goal concrete: fewer repeated corrections across coding,
study and writing workflows, with inspectable and reversible learning. Expand
integrations only after this loop proves useful to actual users.
