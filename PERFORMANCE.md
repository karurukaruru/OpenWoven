# Retrieval performance notes / 检索性能记录

Measured on Windows with local Python 3.13, 2026-09-30. Synthetic data only;
no model calls, credentials or user history.

## Reproduce / 复现

From the repository root after installing the Core:

```sh
python examples/retrieval_benchmark.py --messages 1500 --repeats 9
```

The fixture has 1,500 user turns plus 1,500 replies, with 180 matching historical
user turns. It uses normal SQLite calendar/index backfill, a fixed synthetic clock
and a temporary database removed after the run. Fixture generation, index building
and warm-up are excluded. SQL tracing counts SELECT/WITH statements and adds
overhead in both measurements. Candidate cap: 120. Returned results: 8.

| Same synthetic fixture | Before batching | After batching |
| --- | --- | --- |
| SELECT/WITH statements per retrieval, each of 9 runs | 362 | 5 |
| Median warm retrieval | 7.709 ms | 5.534 ms |
| Min–max | 7.247–9.323 ms | 5.168–5.942 ms |
| Returned IDs | `user_000000` … `user_000007` | Same |

Previously each candidate, reply and daily archive was fetched separately. Now
candidate types, first assistant replies and daily links are loaded in batches,
with an additive `reply_to_id` index. That optimization kept the then-current v8
schema; the current Core uses v11 for later delivery/character features.
Mixed evidence/memory/date queries need additional bounded batches; **5 is this
fixture's count, not every query**. Provenance checks still reject summaries from
excluded messages. Reply quotations now also honor excluded reply IDs. No
long-lived content cache is added, avoiding new stale copies after deletion.

Local median improved about 28% in this sample; SQL round trips fell about 98.6%.
This is not an end-to-end chat benchmark, semantic recall evaluation, LLM token
reduction or guaranteed Android speedup. Do not advertise “98.6% faster chat”.
Timings are informational; tests assert query counts, result order and deletion
behavior, not hardware-specific latency thresholds.

## Android paths / 安卓端处理

- Background delivery fetches one persisted message by ID instead of parsing
  the newest 300 messages. Old source updates no longer depend on the chat window.
  Full reloads still occur on initial load/send/delete; older-chat pagination remains.
- Notification/sound/vibration/feedback toggles no longer close/recreate Core or
  repeat startup maintenance. Timing/greeting-delay/proactive toggles still reload
  Core configuration. This is removed work, not a measured battery/latency claim.

Next profiling targets: full-history parsing, archive maintenance under large
histories, hot-field evidence replay, and the bridge lock across model requests.
Streaming/cancellation need lifecycle tests before changing that lock.

## 2026-10-01 recovery and bounded-work review

- Rolling summaries read at most 256 contiguous messages per maintenance attempt,
  using a conversation/insertion-order index instead of sorting/materializing the
  entire unsummarized lifetime tail. A terminal learning failure no longer blocks
  future summaries; pending/processing inputs remain a hard fence. Raw sources are
  retained, and incomplete/low-information summaries are marked honestly.
- Tokenizer v2 adds Japanese kana/mixed-script/width normalization. Existing raw,
  evidence and summary postings are reindexed in persisted 256-row batches once;
  interruption resumes after the committed batch. Initial upgrade still scans old
  documents and can take time for large databases.
- Concurrent duplicate Android delivery hints now share one reveal/query instead
  of reloading the same reply twice. Task cancel/delete refreshes no longer recreate
  Core. These remove work; no battery or end-to-end speedup is asserted.

Re-ran the same 3,000-message fixture with 9 warm retrievals: each still used 5
SELECT/WITH statements and returned `user_000000` through `user_000007`. Median
6.247 ms, range 5.328–7.206 ms on this run. This is a regression check, not evidence
of a speed gain over the separate September 30 measurement or a phone benchmark.
