# OpenWoven

An experimental Android chat app that remembers conversations, learns how you like to talk, and can start a conversation of its own.

[中文](README.md) · [AUL design](AUL_DESIGN.md) · [Architecture](ARCHITECTURE.md) · [Performance](PERFORMANCE.md) · [GitHub publishing](GITHUB_RELEASE.md) · [Release checklist](RELEASE_CHECKLIST.md) · [Changelog](CHANGELOG.md)

The idea is **AUL (AI User Learning)**: an adaptive user layer that turns
conversation evidence and specific feedback into auditable preferences and
guidance for later LLM replies. It does **not** train model weights.

Status: experimental, single-user prototype. Automated checks validate state
transitions, not long-term user satisfaction or real-model reply quality.
With a remote provider configured, selected conversation and memory context
is sent to that provider. Local-first does not mean the model runs on-device.

## Why this exists

Remembering how to use software was the idea behind an earlier ASM (Agent
Software Map) project. OpenWoven applies a similar idea to communication
preferences: how brief replies should be, when to take initiative, and whether
playful banter or repeated advice is welcome. An interview is only a starting
point; later corrections must be able to change the initial assumptions.

The client also tackles the mechanics of everyday messaging: separate short
bubbles, paced delivery, waiting while the user is composing, and occasional
scheduled openings rather than an immediate wall of text. Generated proactive
openings are bounded to at most three short bubbles. Calendar memory keeps
original messages and retrieves selected excerpts instead of sending all history.

Persona describes the fictional character; AUL describes the user's preferences;
Memory keeps conversation sources; Policy selects guidance for this turn.
Specific feedback such as “too long” updates style. Generic thumbs-up/down do
not identify which style dimension to reinforce. See [AUL design](AUL_DESIGN.md)
for the actual update rules and limitations. The 10/50-question interview is not
a validated psychological scale, and no human-likeness or token/quality saving
claim has been independently demonstrated.

Best fit: developers exploring auditable preference learning and local calendar
memory. The Core is reusable on its own; Android is a reference client, not a
requirement or a finished virtual-character product.

See the [three architecture diagrams and source map](ARCHITECTURE.md) for system
boundaries, memory/learning and scheduled delivery. They describe implemented
flows, not a deployed FCM server or verified model/device behavior.

| Available now | Not yet validated or implemented |
| --- | --- |
| Offline demo, reusable Core, feedback-to-policy loop | Claimed token/quality savings, ideal-character matching |
| Source-linked day/week/month archives and indexed date/keyword recall | Semantic recall, encrypted export or sync |
| Android chat, 10/50-question setup, four UI languages, vision upload path, best-effort scheduling | Production-signed release, FCM backend, streaming, real-device/provider validation |

## Try the learning loop without an API key

Python 3.11+; the core has no third-party runtime dependencies. From this folder:

```sh
python -m pip install -e .
python -m openwoven --db ":memory:" demo
python examples/calendar_memory_demo.py
python -m unittest discover -s tests -v
```

The demo uses synthetic Chinese messages and a deterministic local provider.
It shows preferences changing after corrections, different turn guidance,
auditable evidence, and daily/weekly memory. It is **not** an LLM quality test.
For persistent interactive use:

```sh
python -m openwoven --db companion.db chat
```

Inside chat: `/show aul`, `/show preference reply_length`, `/show audit`,
`/show metrics`, `/daily`, `/weekly`, `/quit`.

## Embed the core

```python
from openwoven import CompanionCore

with CompanionCore(":memory:") as core:
    core.chat("回答短点。")
    core.wait_for_learning()  # Optional barrier for tests; not required for chat.
    result = core.chat_result("今天随便聊聊。")
    print(result["response"], result["aul_version_used"])
    print(core.aul()["interaction"]["reply_length"])
```

`LLMProvider` is replaceable. The included network provider accepts an
OpenAI-compatible chat-completions endpoint. Demos and tests need no credentials
and make no model requests; the first package install may download build tools.
Configure a provider explicitly for real chat.

## What is distinct here?

- Separate Persona, Memory, AUL (AI User Learning), and per-turn Policy.
- Rules-first evidence extraction; optional, gated semantic extraction.
- Explicit feedback changes ten conversation-style dimensions, with provenance.
- Durable raw messages, replayable evidence, bounded prompt projections.
- Asynchronous learning: an in-flight reply uses a frozen committed snapshot.
- Summary source tracking: deleting input invalidates derived memories.
- Automatic closed-day/week/month archives, a calendar browser and paginated
  original quotations. Lifetime lexical/date search uses a SQLite posting index,
  not a newest-500 scan; no embedding or summary-model call is required.
  Candidates, replies and archive links are loaded in batches.
- Persistent latency and token metrics; `usage_source` distinguishes provider
  usage, estimates, mixed values, and unknown legacy measurements.
- Android setup starts with 10 responses: 5 about the user and 5 about the desired
  character, including explicit “Not sure yet”. Offline setup keeps preferences and a
  temporary or manually chosen name. Once configured, the current model can propose
  a profile and eight names on an explicit click, for review before saving.
- The full interview has 50 questions, 25 for each side; extra answers can be added
  later or withdrawn. Unknowns and untouched sliders don't assert preferences.
  Each slider labels the meaning of both 0/1 endpoints and its current value.
  Character generation is bounded and JSON-validated; failures keep the old draft.
  Configured retries may incur costs. Saving provider settings does not generate a character.
  Confirmed fictional profiles remain stable when only user details are updated.
- Simplified/Traditional Chinese, Japanese and American English for app-owned UI,
  help, notification labels and default response language. Original data stays original.
- Saved model selection, per-model manually declared vision capability, and parameter
  help explaining defaults/ranges. A configured vision model enables the system photo
  picker, preview/remove and sending through Chat Completions image_url blocks.
  No broad photo-library permission: only selected images are read. Original limit
  20 MB; private JPEG copies strip EXIF, max edge 1536 and max 2 MB; four images/turn.
  Image bytes are not AUL or text history and old images are not repeatedly uploaded.
  Deletion/reset removes associated copies. Provider support and image fees vary;
  this path was checked with synthetic requests, not a real provider or device.
  Provider reset preserves endpoint, key, models, language, role and chat history.
- Sent user bubbles persist separately and form one turn. Draft text/IME composition
  pauses replies; empty-composer focus/touch resets the default 20s idle wait
  (10–60s adjustable). Only this app's composer is observed. Pending turn jobs persist;
  the unsent-composer gate is process-local and background timing is best effort.
  Typing during generation holds the answer for reuse; new sent content cancels it.
- Daily chat defaults to short, relaxed messages; split bubbles remain separate with
  timing disabled. Ordinary settings expose length (0 brief, 1 detailed, default .30)
  and timezone (blank follows device). Actual local time/offset/zone is refreshed
  before requests and included in text budgeting; image costs are separate.
- Optional durable 60–180s standalone-greeting replies on Android. New content
  joins an old greeting into the turn; additional greeting delay defaults off for new
  installations. Existing explicit switches are preserved.
- Exam follow-ups require an explicit date and end time instead of guessing when
  an exam ends. Unknown times are recorded and clarified; rescheduling/cancellation
  preserve provenance. This is a narrow parser, not a general calendar agent.
- Optional casual openings use recent topics/interests after at least three user turns,
  with the existing one-per-day limit, eight-hour spacing and quiet hours. A new user
  message invalidates old openings; ignored openings don't repeatedly reactivate.
  Background casual generation is gated on app and system notification availability.
- Android 13+ requests notification permission once after setup, with explicit settings
  entry points after denial. Chat follows the latest messages without scroll animation
  and doesn't pull readers away from older history.
- Both editions expose a normal Scheduled messages page: choose device-local date/time,
  exact content (offline) or a topic generated by the current model when due. Pending
  requests can be cancelled. These explicit requests are separate from automatic
  check-in limits but respect quiet hours and expire after a 24-hour window. Delivery
  is to this app and system notifications, not an external messaging service.
- Casual Chinese replies use deterministic natural short-message boundaries, not
  only random splitting. Saved plans survive restarts and background delivery; quoted
  text, numbers, code and explicitly requested documents retain their format.
- The same setup request can distill long answered user questions into AUL keywords.
  Confirmation updates only their source-linked evidence; originals and source times
  stay intact so later chat corrections win. Unanswered/unknown questions are not sent.
- The default input estimate and local summary token threshold are now 5400. Old
  defaults migrate once; other custom budgets remain. Older content is summarized
  locally while the prompt keeps a recent contiguous tail. No extra summary API call,
  no original deletion, and no claim of an exact provider token cap.

These are implementation properties, not claims of superiority to other systems.

See [role-first design and limitations](PERSONA_DESIGN.md). No API key or real
model call is required for offline setup or the checks; generating a model-written
character does require a configured provider. Local replies are examples,
not evidence of LLM quality; language UI support doesn't make every extraction or
calendar rule equally capable in all four languages.

See [memory design and limitations](MEMORY_DESIGN.md) and
[current project comparisons](COMPETITOR_NOTES.md). Calendar compaction uses
structured evidence plus selected quotations, not a model-written narrative.
Keyword search is not semantic recall. Android scheduling is best-effort, not
an exact alarm. Both editions expose the calendar; advanced configuration remains
behind the existing gate. Schema v11 preserves old data, including v10 source-owned
delivery plans and the durable notification outbox, and adds lightweight character
continuity records. The migration does not replay old sent messages.

Offline commands: `archive`, `show monthly`, `search "2026-07-11 keyword"`,
`archive-detail <memory-id> --offset 50`.

## Android reference client

Kotlin/Compose + Chaquopy, Android 8+, arm64-v8a and x86_64. Full and Locked
flavors share the same core implementation but use separate application storage.
The Locked password is a convenience gate, **not** an access-control boundary.
Public binary distribution is Full-only: Locked source remains available for
development and regression checks, but Locked APKs are not uploaded.

Use `openwoven` for new imports and CLI commands. Legacy `adaptive_companion`
imports, `companion` and `COMPANION_*` settings remain compatible. Android keeps
its existing application/storage IDs; Full is labeled OpenWoven Developer.

Both editions offer best-effort system scheduling or a visible, stoppable resident
foreground service. Both now default to resident mode, disclosed at onboarding;
an explicitly saved system-mode choice is preserved. The service starts only from a visible Activity and
does not use wake locks, boot autostart or hidden restart loops. Android can still
stop or delay it. Its declared `specialUse` purpose requires review for Google Play
distribution; approval is not guaranteed. There is no configured Firebase/FCM backend
and no automatic Google-services detection. FCM would need a trusted sender plus
server-side scheduling/generation, authentication and synchronization.

Exact-text schedules remain offline after restoration even with a configured provider.
A scheduled reply and its pending notification are committed together; the resident
loop, worker retry and app reopening retry submission without generating another reply.
Replay respects quiet hours, runtime permission and the selected message channel;
pending notifications expire after 24 hours. Foreground or explicitly disabled app
notifications are handled without later replay. Stable notification identities reduce
duplicate submissions; submission is not a display/read receipt or an exactly-once
guarantee. Deleting raw messages/resetting data removes their outbox rows.

See the [plain-language runtime guide (Chinese)](RUNTIME_GUIDE.md) for actual
formats, delivery semantics and remaining limitations. When greeting delay is enabled
in a Core integration, use `chat_result` and its `deferred`/`scheduled_message` fields,
then execute the persisted job; `chat()` alone does not run a scheduler.

Install Android SDK platform 36, Build Tools 36.0.0, JDK 17, and Python 3.13.
The wrapper pins Gradle 9.3.1; AGP 9.1.1 and Chaquopy 17.0.0 are declared in
the project. See [AGP's compatibility table](https://developer.android.com/build/releases/agp-9-1-0-release-notes).
Chaquopy discovers Python automatically; override with `COMPANION_BUILD_PYTHON`
or `-PcompanionBuildPython=/absolute/path/to/python3.13` if necessary.

```sh
cd android
# Use gradlew.bat in PowerShell; on Unix: sh ./gradlew ...
sh ./gradlew :app:testFullDebugUnitTest :app:testLockedDebugUnitTest
sh ./gradlew :app:lintFullDebug :app:lintLockedDebug
sh ./gradlew :app:assembleFullDebug :app:assembleLockedDebug
```

The first Android build downloads dependencies; offline mode requires a populated
cache. Debug APKs are under `android/app/build/outputs/apk/{full,locked}/debug/`.
Production signing and release hardening remain unfinished.

The Core workflow installs the distribution and smoke-tests isolated
imports on Windows/Linux and Python 3.11/3.13. A manual Android workflow checks
both editions' unit tests and lint without provider keys, builds Full only, and
retains reports and the Full Debug APK for seven days. Locked APKs are excluded.
See [actual hosted runs](https://github.com/karurukaruru/OpenWoven/actions) for
current results; dependency downloads require internet access.
CI artifacts are not a stable public Release. Different machines' Debug signing
keys may prevent update installation; uninstalling loses local history because
export/backup is unavailable. Both Debug application IDs end with `.debug`.

## Known boundaries

- One user/AUL per database, not a multi-tenant service. Conversation IDs do not
  provide user isolation.
- Lifetime indexed search ranks up to 120 lexical candidates. Synonyms, vague
  references and crowded generic terms may miss relevant records; this is not
  semantic search or a guarantee of perfect lifelong recall.
- Rule extraction is largely Chinese. Common negations, quotations and hypothetical
  statements have conservative filters/tests, not comprehensive language understanding.
  List-valued belief retractions and richer conflict resolution remain incomplete.
- Android serializes bridge calls across network requests. Streaming, cancellation,
  and older-chat pagination remain unfinished. Archive-original pagination and
  automatic closed-day/week/month maintenance are implemented. Cancelling display
  or deleting history cannot yet interrupt a network request immediately.
- Preference confidence is a heuristic, not a calibrated probability. No
  independent quality benchmark or claimed 60%-token/90%-quality result exists.
- See [Security boundaries](SECURITY.md) and [Review](REVIEW.md).

## License and contributions

The owner selected [MIT](LICENSE): Copyright (c) 2026 karurukaruru.
Third-party components retain their own licenses.
See [Contributing](CONTRIBUTING.md), the [release plan](OPEN_SOURCE_PLAN.md) and
the [source-vs-APK checklist](RELEASE_CHECKLIST.md). The publication target is
`karurukaruru/OpenWoven`; check GitHub for actual publication and hosted CI status.

For a local source inventory and common secret-pattern check, run
`python scripts/release_preflight.py`. This is not a full privacy/history audit.
The [publishing runbook](GITHUB_RELEASE.md) and [draft release notes](RELEASE_NOTES.md)
separate experimental source publication from production APK distribution.
