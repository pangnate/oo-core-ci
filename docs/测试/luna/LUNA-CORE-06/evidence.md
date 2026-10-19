# CORE-06 source audit

2026-10-19. **PARTIAL: SOURCE-AUDITED / WAIT-BUILD.** No confirmed defect in the inspected scope; no new production patch. This is a reuse candidate, not runtime REUSE. C++/codec assertions executed: 0.

Dependencies: CORE-05 SOURCE-READY, CORE-02 contract, BLD-01-FIX02 isolation. CORE-05 CODEC and BLD-00-FIX01 remain unsatisfied. Resolve this card's commit with `git log -1 -- docs/测试/luna/LUNA-CORE-06/evidence.md`.

Inspected real shared C++ paths:

- `Binary_pPrWriter::WriteSpacing`: AfterLines48 and BeforeLines49 are Long payloads from GetValue, gated by IsInit. Physical twips and auto flags have separate records, not an else-branch that removes line units. `Binary_pPrReader::ReadSpacing` initializes each Lines field and assigns GetLong without conversion.
- `CSpacing` DOM/stream readers, ToString and Merge all retain both line properties independently. Presence guards retain explicit zero and false auto flags. Normalization to mm is absent in these paths.
- `Binary_rPrWriter::Write_rPr` writes existing CompressText44 only when run `m_oW/m_oVal` exists; it writes the raw value. `Binary_rPrReader` initializes that same property and sets GetLong. `CRunProperty` XML output and Merge retain this field.
- Shared paragraph/run routines serve direct formatting, defaults, styles, numbering and property-change snapshots. Source dispatch anchors are recorded, but no actual document in those containers has been converted in this audit.

`audit-plan.json` and generated `source-audit.json` identify exact inspected files, SHA256 and matching source lines in a newly replayed candidate staging. The extractor only finds anchors; the conclusions above come from manual function-body review. It does not test the serializer. Existing seven patches are consumed as candidates only; no patch006 or empty patch is created. Official/local input and protected POC hashes are recorded in the staging/isolation receipt.

Reproduce source evidence: `python tests/core-features/audit_source_anchors.py --staging vendor/work/codec-audit-dev-20261019 --plan docs/测试/luna/LUNA-CORE-06/audit-plan.json --output docs/测试/luna/LUNA-CORE-06/source-audit.json`.

Pending: implement/run the real-Core `word-existing` case for the matrix in `acceptance.json`, compare actual BIN bytes/XML over two generations, hash matching executable/DLL/SDK/input/output, and verify inherited zero plus revision paths. No UI, layout or PDF completion is claimed. Actual CODEC acceptance is still required before dependent runtime cards close.
