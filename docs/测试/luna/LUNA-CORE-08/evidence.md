# CORE-08 source audit and narrow candidate repair

2026-10-19. **PARTIAL: SOURCE-READY / WAIT-BUILD.** No real compilation, CODEC, native protection enforcement or PDF verification. C++ assertions executed: 0. Resolve commit with `git log -1 -- patches/core/016-word-protection-source-omissions.patch`.

Source dependencies: CORE-06 audit `73af6e00`, CORE-07 SOURCE-READY, CORE-02/FIX02 contracts. Runtime dependencies 06/07 CODEC and matched Core 10 remain pending.

Confirmed defects, established by complete function-body inspection:

1. `CDocProtect::fromXML(CXmlNode&)` was an empty TODO. A DOM caller therefore loses even a minimal initialized enforcement/formatting/algorithm/hash/salt input. It now reads existing native model fields and the aliases accepted by the stream reader. Canonical names take precedence in the DOM; conflicting alias combinations retain the stream parser's historical order-sensitive boundary and are not claimed cross-parser-equivalent. No new algorithm or password data is generated.
2. `CSectionProperty` already parses and emits `w:formProt`, but `WriteSectPr`/`Read_secPr` contain no such field. Minimal source-level counterexample: an initialized `formProt=false` or true is absent from BIN and cannot be reconstructed. The candidate adds presence-aware section tag200 and symmetric one-byte Bool handling; malformed size/value fails. Existing official section tags0–15 are unchanged. The new parent-scoped private allocation and legacy-JS limitation are explicitly registered in `docs/协议/Core原生节保护_候选增量.md`.

The four-file patch016 is appended after015 without renumbering earlier patches. No applied Core snapshot is committed. It only changes DocProtect DOM parsing and native section codec; no API, dynamic identity, Space policy or history protocol is introduced. No default POC manifest/profile/lock or workflow is changed.

Other inspected paths have existing symmetric support: Permission0–5 includes id/displacement/columns/ed/edGrp, with independent presence guards allowing ed and group together and zero columns; permEnd keeps its native id/displacement fields. All seven native group values already map both ways. Existing document-protection model fields have Settings writer/reader channels; enforcement/formatting false and spinCount0 are presence-gated. Style Locked has a separate presence marker on the reader. Shared section writer/reader also serves property revisions. XML spelling is already handled by patch007. These are source findings, not full fidelity or security enforcement acceptance.

`audit-plan.json`/`source-audit.json` bind inspected functions to actual staging file hashes/line anchors. `patch-replay.json` records the entire eight-patch candidate set checked/applied with whitespace rejection in fresh touched-file copies, matching the development source after newline normalization. `source-receipt.json` binds the source candidate set and unchanged protected POC hashes. Original source is not edited; no download/prepare, build, Actions trigger, publish or push.

Pending real tests are in `acceptance.json`: both parsers and two-generation DOCX/BIN roundtrip, native scope/ids/permissions, section revisions and unrelated fields. Do not turn source anchors into CODEC PASS. Old SDKJS may drop new section200; CORE-25 and the product artifact contract must expose that boundary before mixed-version use. Original card remains PARTIAL.
