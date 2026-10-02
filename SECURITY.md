# Security and privacy boundaries

This is an experimental single-user companion, not a hardened hosted service.
Do not use it for medical, legal, financial or crisis-care decisions.

- Android encrypts saved API keys using Keystore. The SQLite conversation/AUL
  database itself is **not** encrypted by the application.
- App data is excluded from Android automatic cloud backup and device transfer
  by manifest and XML rules. Removing the app or losing the device may therefore
  lose local history. An encrypted user-controlled export is still a future task.
  Backup/transfer behavior must still be tested on actual target devices.
- A configured remote provider receives selected conversation, profile and
  memory context. Local-first does not mean all computation stays on the device.
- `MIOKIRISHIMA` is a publicly documented shared convenience password. PBKDF2
  does not make this shared password secret. Advanced route guards are UX gates;
  the Full flavor and local code modifications can bypass them.
- Deletion removes the raw messages, linked replies, evidence, feedback, metrics,
  related schedules and source-linked summaries. Legacy summaries without full
  provenance are conservatively invalidated. Audit history for affected belief
  fields is removed as it can contain forgotten facts in old/new values.
- Deletion is logical, **not** forensic secure erasure. SQLite pages/WAL, prior
  device backups, screenshots, notifications and remote provider retention are
  not guaranteed to be erased. No real user data is needed for tests/demos.
- Memory is quoted data in prompts, not authority. Prompt-injection resistance
  and provider-output safety need adversarial evaluation, not just this instruction.
- Use a separate database per user. The current schema has one AUL singleton;
  a conversation ID is not a tenant-security boundary.

Before publishing, inspect the staged files for keys, real conversations,
databases including WAL/SHM files, private endpoints, and production signing keys.
Ignore rules help future commits; they do not clean already tracked files/history.

## Reporting a vulnerability

Private vulnerability reporting is enabled for the public OpenWoven repository.
Use [Report a vulnerability](https://github.com/karurukaruru/OpenWoven/security/advisories/new)
for security reports; ordinary reproducible bugs can use Issues.
Do not disclose credentials, real conversations or exploitable private user data
in a public issue. Submit a minimal synthetic reproduction, affected version and
expected/actual behavior. No fixed response time or professional security support
is promised for this experimental project.
