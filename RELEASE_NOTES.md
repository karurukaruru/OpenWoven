# OpenWoven release notes draft — v0.1.0

**No tagged GitHub Release yet.** This is a draft, not a statement of repository
visibility. Use the body below only after the checks in
[GITHUB_RELEASE.md](GITHUB_RELEASE.md). Confirm the target commit, copyright,
private security-report channel, hosted CI and selected attachments first.
Remove this drafting paragraph; replace document links with actual tag URLs
in the chosen repository when copying into a GitHub Release body.

---

## OpenWoven v0.1.0 — Experimental source release

OpenWoven is an experimental Android chat project with a reusable Python Core:
calendar memory, short paced messages, proactive openings and **AUL (AI User
Learning)**. AUL learns auditable preferences from evidence and specific
feedback, not model weights. An interview supplies a starting point rather than
a fixed personality label; later corrections can change the initial assumptions.

### Included

- OpenWoven app/distribution/CLI branding; legacy Python imports, the `companion`
  command and Android installation/storage identifiers remain compatible.
- Reusable Python Core (Python 3.11+, no third-party runtime dependencies).
- No-key demos: feedback → evidence → AUL → reply policy; day/week/month recall
  and source-linked deletion.
- SQLite persistence, lexical/date retrieval, budgeted context and lightweight
  character continuity instead of sending every stored record per turn.
- Android Full/Locked reference clients: four UI languages, 10/50-question setup,
  separate short bubbles, paced delivery and input-idle reply gating.
- Explicit scheduled messages and low-frequency proactive topics; stoppable
  resident service/system-work fallback, permissions and notification outbox.
- Generated proactive openings use at most three short, paced bubbles; exact
  user-scheduled original text is preserved. Tied schedule timestamps have stable
  insertion ordering rather than relying on platform clock resolution.
- User-selected image uploads for models explicitly marked vision-capable.

### Try without a model key

From the tagged source checkout:

```sh
python -m pip install -e .
python -m openwoven --db ":memory:" demo
python examples/calendar_memory_demo.py
python -m unittest discover -s tests -v
```

Installation may download build tooling. Demos/tests use synthetic data and local
providers, not real-model quality measurement. See [README.en.md](README.en.md)
and [README.md](README.md) for usage and builds.

### Known limitations

Experimental single-user project, not production or app-store ready. Search is
lexical, not general semantic recall. Tokens are estimated; no 60%-cost/90%-quality
improvement is established. Real model quality, long-term satisfaction and
target-device behavior remain unverified.

Android scheduling is best-effort; system restrictions may delay/stop delivery.
No configured FCM sender/backend, streaming, encrypted export or sync.
The database is not application-encrypted; remote providers receive selected
context. Uninstall/device loss may lose history. Deletion is logical, not forensic
erasure or recall of provider-held data. The publicly documented Locked password
is a convenience gate, not security.

### Optional binary attachments

This release is source-first. A wheel is for Python, not Android. Any optional
Android downloads are **Debug / experimental** reference builds, not production
APKs; Android 8+, arm64-v8a/x86_64. Public Android attachments are **Full only**;
Locked source remains in the repository but Locked APKs are not uploaded.
Binary downloads should be accompanied by their build-source
details, third-party notices and `SHA256SUMS.txt`.
Different Debug signing keys can prevent updates; uninstalling loses local data.
Production signing/device/provider acceptance are separate milestones.

### License and feedback

Project source: MIT. Third-party components retain their own licenses.
Report reproducible bugs with synthetic examples only; no keys, databases or real
conversations. Vulnerabilities go to the private channel documented in the
released `SECURITY.md`, not a public issue.

中文概要：首版是可复用的偏好学习/日周月记忆 Core，附 Android 参考客户端。
无模型 Key 可验证机制；不承诺真人感、统一节省率或后台准点必达。
如附 APK，它仍是 Debug 体验版，不是正式签名版。
