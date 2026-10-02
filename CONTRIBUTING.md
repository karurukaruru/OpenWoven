# Contributing

This is an experimental source project, not a production APK release. The owner
selected MIT; the confirmed copyright holder is karurukaruru (2026).
Third-party components retain their own licenses.

Publishing steps are in [GITHUB_RELEASE.md](GITHUB_RELEASE.md); the first-release
draft is [RELEASE_NOTES.md](RELEASE_NOTES.md). Run
`python scripts/release_preflight.py` for a local approved-source inventory.
`--for-publication` rejects the unfinished copyright notice; `--check-index`
also checks tracked paths and working/index equality, not Git history.
Reports under `release-dist/` are local review artifacts, not repository source.

Keep the three diagrams and source links in [ARCHITECTURE.md](ARCHITECTURE.md)
aligned with implemented boundaries. The Android shrinker configuration is a
required source file even while shrinking is disabled; do not omit it from a
source release or enable unverified shrinking as a documentation change.

Start with the zero-key demo in README.en.md. For core changes, add regression
tests and run `python -m unittest discover -s tests -v`. For Android changes, run
both flavor unit tests, lint, and debug assembly as described in README.md.
For retrieval changes, run `python examples/retrieval_benchmark.py` and compare
SQL counts, source/deletion behavior and result order. Timings are informational;
do not add hardware-specific latency gates.

Keep the core small and provider-independent. Preserve raw conversation data,
source provenance, deterministic aggregation, and the distinction between
Persona, Memory, AUL and Policy. Avoid new cloud services or dependencies unless
a measured problem calls for them.
See [AUL_DESIGN.md](AUL_DESIGN.md) for the meaning of AI User Learning, feedback
limitations and the distinction between mechanism checks and model-quality tests.

Useful initial contributions: Chinese negation/quotation regression cases,
indexed historical retrieval, stream/cancellation lifecycle tests, accessible
localized UI, and reproducible synthetic evaluation fixtures.

Bug reports should include steps, expected/actual behavior, version, and a
minimal **synthetic** example. Do not attach personal conversations, database
files, API credentials, signing material, or unredacted provider error logs.

The prepared Core-test workflow uses no model API calls and requires no API keys.
It installs the distribution (not an editable link) and smoke-tests isolated imports.
A separate manual Android workflow uses no provider or production signing secrets.
It tests/lints both editions, but builds and uploads Full only; do not add Locked
APKs to artifacts or Releases. Current hosted results are in
[Actions](https://github.com/karurukaruru/OpenWoven/actions); local and hosted
checks are different evidence.
First installs/builds may download tools/dependencies. See RELEASE_CHECKLIST.md
before treating this as a released package or APK.
