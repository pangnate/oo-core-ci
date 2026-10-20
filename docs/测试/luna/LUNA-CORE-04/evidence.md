# CORE-04 — source implementation receipt

2026-10-19. **PARTIAL: SOURCE-READY / WAIT-BUILD.** C++ and codec assertions executed: 0. No compilation or real conversion result is claimed.

- Commit: resolve `git log -1 -- patches/core/004-word-character-indents.patch`. Source dependency CORE-03 is `5cd70e30`; CORE-02 and BLD-01-FIX02 source receipts also apply. CORE-03 CODEC and BLD-00-FIX01 remain pending.
- Base/order: pinned official Core, then 003, then 004; hashes and dependency order in `source-replay.json` and the opt-in candidate series.
- Before: the shared paragraph indentation codec writes physical twip fallbacks and drops all four character-unit fields. After: Ind(tag 1, Variable) additionally contains LeftChars206, RightChars207, FirstLineChars208, HangingChars209 as Long integer hundredths of a character. `IsInit`, not truthiness, gates writing, so zero remains present. Each field is independent, with no mm conversion, sign clamp or first-line/hanging conflation. Reader rejects a character payload whose length is not 4.
- Source audit: native StartChars/EndChars/FirstLineChars/HangingChars already have XML parsing, serialization and presence-aware merge support; `SimpleTypes::CDecimalNumber` uses an `int` and existing `SetValue`/`GetValue`, including negative values. Existing logical start/end mapping and Transitional left/right XML output are retained. Shared pPr paths cover direct formatting, styles, numbering and revisions without editing those consumers. Physical fallback and its existing first-line/hanging precedence are unchanged.
- Validation: both on-disk patches applied in sequence to fresh task-owned copies of all four touched files from the locked pristine source, and normalized text matched the development tree. All actual `git apply --check`/`git apply` exit codes are 0 in `source-replay.json`; this verifies patch replay, not C++ behavior. Default POC input hashes still match the initial capture. Pending full-tree replay is recorded with the final candidate set.
- No original Core source, POC staging, SDK, runtime, workflow, default patch series or profile changed. No Actions execution, push or deployment.

## Pending real acceptance

Run `word-chars` on matching Core 10 x2t/DLLs through two DOCX/BIN generations, and assert actual nested BIN tags/lengths plus XML integer values and presence. `acceptance.json` records the unexecuted matrix. The future runtime harness must execute Core, not reproduce the codec in Python; source-only checks cannot close this card. Layout is CORE-22.
