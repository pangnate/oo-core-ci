# CORE-09 source audit and narrow candidate repair

2026-10-19. **PARTIAL: SOURCE-READY / WAIT-BUILD.** No C++ compile, CODEC or real PPTX conversion. C++ assertions executed: 0. Resolve commit with `git log -1 -- patches/core/017-slide-paragraph-stream-bools.patch`.

Source dependencies: CORE-02/FIX02 and this round's completed CORE-08 source receipt `54f9a1af`; the matched Core 10 runtime is still pending.

Confirmed source defect: `TextParagraphPr` has eaLnBrk/hangingPunct/latinLnBrk members, DOM readers, XML writers, Merge/assignment and native PPTY2/4/6 records, but its shared streaming `ReadAttributes` did not read any of these attributes. Thus a streaming caller with the minimal XML counterexample in `acceptance.json` leaves all three fields uninitialized and omits their output records, including explicit false. Paragraph and TextListStyle streaming callers reach this function. Patch017 adds exactly the missing three attribute mappings in one production file; no tags, alignment values, units, layout algorithm or model fields change.

Other source findings: seven `TextAlign` values map bijectively through existing native codes0–6 (dist=1). Nullable Bool writes use IsInit, not truthiness; reader assignment initializes false. TextSpacing has separate Pct0/Pts1 Int records and raw GetLong reads, and nullable Int writes retain zero. Existing Normalize clamps only the native Pts range; it does not convert valid Pct values into Pts. Shared Merge selects present current paragraph properties and retains false. None of these correct valid-input paths was changed.

The card's three East Asian Booleans are eaLnBrk, latinLnBrk, hangingPunct; rtl10 is a separate existing regression property. The hash-pinned initial contract snapshot listed rtl in its three-Bool list; this source receipt records the concrete distinction without rewriting that POC input. Both DOM and streaming/PPTY behavior for real documents still require execution. Invalid dual-unit, malformed enum and out-of-range inputs are not proven supported or fixed by this patch; do not claim general malformed-input coverage.

`source-audit.json` extracts actual file hashes and line anchors from the isolated development tree. `patch-replay.json` records all nine candidate patches checked/applied in order with whitespace errors rejected, then compared with development source after newline normalization. This confirms reproducible source, not serialization. `source-receipt.json` records candidate hashes and unchanged POC inputs. No direct `core/` edit, default manifest/profile/lock/workflow change, build, Actions trigger or push.

`acceptance.json` specifies both real parsers, seven alignments, all27 tri-state Bool combinations, inheritance, native PPTY records, spacing0 and two saved generations across applicable containers. A real C++/x2t harness must consume these expectations after the runtime gate; source anchors cannot close CODEC/REUSE. Native layout/new Changes remain CORE-24.
