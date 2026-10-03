# Changelog

## v0.2.0 — 2026-10-03 (experimental)

- Android role library: create, preview imports, export role-only ZIPs and switch characters while retaining separate chats and memory. Preserve the legacy database and image paths.
- Shared bounded ZIP codec and basic V1/V2/V3 JSON/PNG card conversion. No imported scripts, prompt overrides, lorebooks, user profiles or credentials.
- Keep imported character seeds separate from source-linked learned backstory, so deletion still removes facts derived from deleted chats.
- Local Web client for Windows/macOS/Linux: shared Core, text chat, composer-aware waiting, paced bubbles, role packages, scheduling and memory inspection. Loopback-only with same-origin/session/CSRF checks; keys remain in memory.
- Chinese/English introduction now briefly explains AUL and natural message pacing. Add role-package compatibility documentation.

## v0.1.0 — 2026-10-03 (experimental)

Published as a [GitHub prerelease](https://github.com/karurukaruru/OpenWoven/releases/tag/v0.1.0),
with an Android Debug APK, SHA256 checksums and third-party notices.
The APK was built from `e0533af0660111c1b060b351b2e5ba14778d3378`.

- Rename the app, docs, distribution and CLI to OpenWoven; retain legacy Python
  entry points and Android identifiers for installation/data compatibility.
- Auditable evidence → AUL → interaction-policy loop, corrections and
  source-linked deletion, persisted in SQLite.
- Daily/weekly/monthly archives, keyword/date recall, bounded context,
  incremental lexical-index maintenance and lightweight character continuity.
- Android Full/Locked, multilingual setup, image request path, input-aware
  replies and independently paced chat bubbles.
- Persistent explicit/proactive scheduling, permissions, quiet hours and
  notification outbox; best-effort resident/system background modes.
- Generated proactive openings always use at most three short, independently
  paced bubbles, even for technical/advice topics or overlong model output.
  Saved history/notifications retain only the bounded text; omitted fictional
  backstory is not archived. Explicit scheduled original text stays unchanged.
- No-key demos, synthetic tests, package smoke checks, contribution templates,
  read-only CI/candidate workflows, runbook and draft release notes.
- Approved-source inventory and selected artifact checksums. MIT holder: karurukaruru.
- AUL (AI User Learning) design and blog-inspired Chinese/English introduction,
  with explicit limits on feedback attribution and unvalidated long-term effects.
- Stable scheduled-message ordering when creation/due timestamps tie, including
  Windows clock-resolution regressions; Full-only Android artifact distribution.
- Model-written weekly summaries using the configured provider, bounded inputs,
  persistent retry throttling and source revalidation before saving. Daily,
  monthly and rolling structured records remain local; originals are retained.
- Concise Chinese/English product introductions and packaged third-party notices.
- Three Mermaid architecture diagrams with source maps; the architecture document
  and Android ProGuard configuration are required in the source-release inventory.

See [RELEASE_NOTES.md](RELEASE_NOTES.md) and
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) for remaining conditions.
