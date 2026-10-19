# CORE-10 source audit and narrow VML repair

2026-10-19. **PARTIAL: SOURCE-READY / WAIT-BUILD.** No compiled C++ test, DOCX/PPTX roundtrip, Native layout, PDF or print result. C++ assertions executed: 0. Resolve commit with `git log -1 -- patches/core/018-vml-ideographic-text-direction.patch`.

Source dependencies: CORE-02/FIX02, executed after CORE-09 source commit `336fe33e`. Matching Core 10 runtime and real CODEC tests remain pending.

Confirmed source defect: the VML CSS parser already recognizes `layout-flow:vertical-ideographic` as `csslayoutflowVerticalIdeographic`, but the drawing converter only sets a BodyPr direction for `csslayoutflowVertical`. With the ideographic token alone, it leaves direction absent/default horizontal. Patch018 changes only that condition/assignment in one production file: vertical-ideographic maps to existing eaVert, vertical remains vert, and the following existing bottom-to-top override still selects vert270. The existing copy to both `oTextBoxBodyPr` and `txBody->bodyPr` is retained. No native enum number, text layout algorithm, font bridge, rotation or frame geometry is invented.

Other audited paths are reuse candidates:

- BodyPr DOM and streaming readers, XML writers and Merge all retain vert; PPTY uses native tag17 and native enum values for all seven existing modes. Insets and separate body fields have independent channels. Normalize does not replace a valid eaVert token.
- PPTX TxBody stores BodyPr in record0; modern Word Shape reads unqualified bodyPr into `oTextBoxBodyPr`, emits the wps namespace and stores/reads the dedicated native body-properties record. Legacy converted text shares that body path. Both Word and Slide paths were inspected, rather than extrapolating PPTX results to Word.
- Word Document drawing writer delegates raw/modern drawing objects to the shared DrawingConverter; the reader uses SaveObjectEx to reconstitute them. Legacy VML may be normalized to modern DrawingML on export: only semantic direction is the acceptance goal, not identical XML syntax.

The source mappings are recorded in `audit-plan.json` and actual line/file hashes in `source-audit.json`. `patch-replay.json` records all ten candidate patches checked/applied with whitespace rejection in fresh pristine touched-file copies, matching development source after newline normalization. `full-candidate-replay.json` records complete official-tree replay and unchanged original/local/Poc-input fingerprints. This is source validation, not C++ UNIT or CODEC. No original Core or existing POC staging was edited; no default manifest/profile/lock/workflow changed and no download/prepare/build/Actions/push was run.

Source infrastructure regression: `python -m unittest discover -s tests/core-features -p 'test_*.py' -v`, exit0, 45 tests passed. These tests validate the existing Python infrastructure/default baseline; they do not execute the new protection, Slide or VML code. The new source extractor was run on each card's plan; it finds text/hash anchors and does not prove behavior.

Reproduce source evidence: `python tests/core-features/audit_source_anchors.py --staging vendor/work/codec-audit-dev-20261019 --plan docs/测试/luna/LUNA-CORE-10/audit-plan.json --output docs/测试/luna/LUNA-CORE-10/source-audit.json`. Reproduce full replay with `tests/core-features/replay_candidate_source.py`, explicit candidate series/source and a new destination under vendor/work.

Pending matrix: `acceptance.json` requires actual Core DOM/stream and two saved DOCX/PPTX generations, including legacy VML, all native modes and unrelated object/relationship/geometry fields. Horizontal-ideographic and contradictory legacy styles are not newly implemented or declared supported here. Valid direction storage does not prove upright CJK/Latin glyph behavior, pagination, Native PDF or system printing; those remain later gates. Original card stays PARTIAL.
