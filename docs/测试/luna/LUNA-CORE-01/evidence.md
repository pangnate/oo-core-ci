# LUNA-CORE-01 evidence — reproducible fixtures and source runner

Date: 2026-10-19
Status: PASS for source-level fixture and runner checks on Windows; no Native Core build/load claim.

## Source templates and generated corpus

- The three base packages were copied from `D:/docservice/idp-all/idp-example/public/templates/{blank.docx,blank.pptx,blank.xlsx}` and retained as `source-blank.*` inputs. Their original hashes are frozen in `tests/core-features/fixtures/manifest.json`.
- `generate_fixtures.py` uses those checked-in copies by default, so regeneration does not depend on the idp checkout. `--source-root` can explicitly refresh the source copies from another matching template directory.
- Generated files are the Word, Slide, and Sheet OOXML packages plus a deterministic valid PNG and a deliberately malformed PNG. The XLSX has four sheets, shared background media, a filled cell, gridlines disabled, multiple-page data, and repeated print titles.
- Word covers the full 4 Chars × 6 Bool value matrix (1,024 combinations), explicit zero/false, line spacing values, TextScale, distributed alignment, and paired permission markers. Slide covers seven alignment values × eight Bool combinations, Pct/Pts spacing, and horz/vert/vert270/eaVert directions.
- Fixture manifest SHA-256: `272ca7c91544ed95982d6be125da715af958b7f89e3e3bb0aa1666f3d9f71bdf`. Two consecutive generations produced the same manifest and output hashes.

## Runner behavior and checks

- `scripts/core_features.py` registers `baseline` and `fixtures`; unknown/unimplemented cases fail non-zero. Both use a source-level Core 10 profile and verify locked input hashes. The baseline replay checks the pinned ref/tree hash, absence of feature patches, declared build patch/overlay, runtime-version caveat, and reruns Windows `verify_vendor.py`.
- Fixture checks parse every package XML part, test ZIP CRCs, resolve internal package relationships, validate all matrix values and expected package parts, and validate PNG chunk CRCs. The malformed PNG is required to fail validation.
- Each case runs in a separately created process group. Timeout handling terminates only the recorded runner-owned process tree; logs redact password/token/authorization values. Tests cover timeout isolation against an unrelated live process, log redaction, result PID logging, hash drift, platform mismatch, unknown cases, and zero assertions.
- `python scripts/core_features.py --case baseline --platform windows-amd64 --profile tests/core-features/profiles/source-windows.json --timeout 120` passed with 16 assertions.
- `python scripts/core_features.py --case fixtures --platform windows-amd64 --profile tests/core-features/profiles/source-windows.json` passed with 168 assertions.
- `python -m unittest discover -s tests/core-features -p 'test_*.py' -v` passed (8 tests).

## Scope boundary

This verifies deterministic package structure and test-runner behavior without the local Native binaries. It does not establish that X2T opens the generated files, nor does it validate PDF, printing, or rendered appearance; those remain with later build/runtime cards. This card is Windows-only. Linux-specific reusable inputs are deferred to the Linux phase and the user-designated `D:/workspace/only9-merge/docker-tools` source; no Linux artifact was copied or tested here.
