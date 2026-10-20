# CORE-05 — source implementation receipt

2026-10-19. **PARTIAL: SOURCE-READY / WAIT-BUILD.** No C++ build, x2t run, CODEC, Native layout or PDF result.

- Commit: resolve `git log -1 -- patches/core/005-word-east-asian-booleans.patch`. Source dependency CORE-04: `eb8f71ed` (which consumes CORE-03 `5cd70e30`); CORE-02 and BLD-01-FIX02 source contracts apply. CORE-04 CODEC and BLD-00-FIX01 remain pending.
- Source change: shared pPr codec now writes/reads Kinsoku200, WordWrap201, OverflowPunct202, TopLinePunct203, AutoSpaceDE204 and AutoSpaceDN205 as Byte-length Bool payloads. Presence alone controls writing; explicit false is serialized as zero, absence is omitted. Reader rejects non-byte payloads and values other than 0/1 before initializing a field. Unknown tags retain the existing generic skip path.
- Existing CParagraphProperty XML DOM/stream parsing, XML output, Clear/IsNoEmpty and Merge cover all six fields already; Merge selects the initialized current property, including false. No model, copy or normalization change was justified by the source audit. Shared consumers cover docDefaults, style, numbering, direct pPr and pPrChange. No Slide tag, feature bit, public ABI, font bridge or SDKJS change.
- Source baseline/order, patch hashes, all actual check/apply commands, output file hashes and successful complete three-patch scoped replay: `source-replay.json`. The replay text matches the development source including BOM after newline normalization; this is not a serialization test. C++ assertions executed: 0.
- Default baseline/series, POC profile, V8/vendor locks and workflows retain their captured hashes. No POC staging or official Core input is modified; no Actions run, publish or push.

## Pending real acceptance

Run `word-east-asian` on a matching Core 10 development runtime, checking nested BIN bytes, false/absence and XML preservation over two generations. All 729 combinations of six tri-state properties, inherited true overridden by false, mixed character fields, revision snapshots, malformed new payloads and unknown-tag following-field behavior are pending (`acceptance.json`). The case is not implemented by this source-only delivery. A future real-Core harness must consume these expectations; source scanning does not close the card. Actual East Asian layout remains CORE-22.
