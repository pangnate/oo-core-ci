# CORE-03 — source implementation receipt

2026-10-19. **PARTIAL: SOURCE-READY / WAIT-BUILD.** No C++ compilation, x2t execution, CODEC, Native or PDF acceptance.

- Implementation commit: the commit containing `patches/core/003-word-distributed-jc.patch`; resolve with `git log -1 -- patches/core/003-word-distributed-jc.patch` (avoids a self-referential commit hash).
- Dependencies: CORE-02 source contract and BLD-01-FIX02 staging evidence. Build dependency BLD-00-FIX01 remains unsatisfied.
- Base: official Core `ed63e94de814ff1d4ea28cddfaba6939bc9df9ed`. A new full staging was created from the pristine source recorded by FIX02, with source fingerprint before/after `cc16fb1824a7788140aa76064c6714d803e51deb90205fe8d625664f508ab5f6`; original empty-feature staging fingerprint `52c0c24ea72fade14c4e36e3bc1572873dc226906e1032e3aa216237c4afd4d7`.
- Before: paragraph `jcDistribute` writes Justify=3; reader has no value 4. After: existing Jc tag 5 writes/reads Distribute=4 using the native `jcDistribute` enum; the original 0–3 mappings are retained. `thaiDistribute` retains its prior Justify mapping and is not mapped to the new distributed algorithm. Unknown Jc payloads and invalid payload lengths return the existing reader error before initializing an alignment.
- Source review: direct paragraphs, defaults, styles, numbering and `pPrChange` all call the shared paragraph writer/reader. No table alignment, public ABI, SDKJS or layout implementation changed. `CJc::SetValue(EJc)` is supplied by the existing simple-type macro.
- Patch identity, full candidate order, actual replay commands/exit codes and output hashes: `source-replay.json`. All listed `git apply --check` and `git apply` commands exited 0; four touched source files match the development copy after newline normalization. This is patch replay, **not UNIT**. The initial replay comparison encountered CRLF/LF differences from staging attributes; the retained successful replay pins `core.eol=lf` and compares normalized text including BOM. No C++ assertions have run (0).
- Only the opt-in `series-word-candidate.json` includes this patch. Default `series.json`, baseline, source profile, V8 lock, vendor lock and workflows retain their captured hashes. No POC tree, original `core/`, SDK or runtime file was edited; no Actions run was triggered.

## Pending real acceptance

Run case `word-jc` with the matching Core 10 development profile after BLD-00-FIX01. The runtime case is not implemented by this source-only delivery; it must fail or remain unregistered until a real x2t harness exists. Planned assertions are in `acceptance.json`, with execution explicitly NOT-RUN. Verify actual BIN bytes and DOCX XML through two conversions, inheritance and revision paths; do not accept source scans as a conversion result. Hash the executable, loaded DLLs, patch set, SDK, inputs and outputs. Layout/PDF remains CORE-22.
