# CORE-07 — source implementation receipt

2026-10-19. **PARTIAL: SOURCE-READY / WAIT-BUILD.** C++/codec assertions executed: 0. No compiled C++ DOM/stream parser, x2t, Native or PDF execution result.

- Commit: resolve `git log -1 -- patches/core/007-word-permission-xml-spelling.patch`. Source dependencies are CORE-02 and BLD-01-FIX02; implemented after CORE-05 source commit `7bef1d53` as requested. The patch itself is independent of 003–005 and touches only `CPermStart`/`CPermEnd` in `Annotations.cpp`. BLD-00-FIX01 runtime dependency is pending.
- Before: both marker readers/writers use incorrect `displacedbyCustomXml`. After: DOM and streaming readers accept standard `displacedByCustomXml` and the old alias, and writers emit only the standard name. Both paths give standard spelling precedence when both attributes exist. DOM uses short-circuit lookup; streaming buffers the legacy value until all attributes have been examined, so XML attribute order cannot change the result. Missing attributes preserve existing presence behavior. Existing next/prev parsing and invalid-value fallback are unchanged; an invalid standard attribute does not fall back to a valid legacy alias. No identity, column, group or protection policy is added or rewritten.
- Standard-wins is the source candidate's explicit resolution of the previously unspecified spelling conflict, now recorded in the card and `acceptance.json`. The hash-pinned CORE-02 POC contract/profile is not rewritten by this candidate.
- `source-replay.json`: all four candidate patches checked/applied in order against task-owned pristine copies of their four touched files; all commands exited 0. Result matches development source after newline normalization. The final scoped replay also uses `--whitespace=error-all` to check actual C++ additions, rather than unified-diff context formatting.
- `full-candidate-replay.json`: a second **complete 21,117-file official-source staging** applied CI corrections → 003/004/005/007 → branding overlay via the existing `stage_core_source` API. Official source fingerprints before/after agree. Final staging fingerprint: `9a674f6f9b6f72aea97ba8d86903622386b51db80f1542f0083fa019b4458b51`. All four touched files match development source after newline normalization.
- Original local `core/` inventory before/after: 21,117 files, `bd93e508a736b8c99948073354262fc883548c7ff4e34d8d395b54f64d739953`. Default baseline/series, source profile, V8/vendor locks and every workflow/action retain their captured hashes. Existing POC staging was not used as a development tree. No build, push, Actions trigger, deployment or publish.
- Python infrastructure regression: 45 tests passed; details, including the initial candidate-discovery failure and its correction, are in `../word-candidate-isolation.md`. This is not evidence of C++ feature execution.

## Reproduce source replay

The full replay was run locally through the existing stager API with explicit `patch_series`; the retained receipt records the actual source/destination and hashes. The following committed wrapper exposes that same call for future reruns. Destination must be new and under `vendor/work`; existing destinations are refused. No POC profile is changed:

```powershell
python tests/core-features/replay_candidate_source.py --series patches/core/series-word-candidate.json --source vendor/work/core-official-poc-20261019-01/unpacked/core-ed63e94de814ff1d4ea28cddfaba6939bc9df9ed --destination vendor/work/word-candidate-review-NEW
```

## Pending real acceptance

Run `permission-xml` using compiled real Core DOM and streaming readers plus matching Core 10 x2t/DLLs. Both marker types, next/prev, absent fields, each alias alone, same-value aliases, conflicting aliases in both orders, escaping, native ids/columns/ed/edGrp and DOCX/BIN two-generation preservation remain unexecuted (`acceptance.json`). Do not implement the parser in a Python test and call it C++ validation. CORE-08 remains WAIT-DEP until the actual CODEC receipts exist.
