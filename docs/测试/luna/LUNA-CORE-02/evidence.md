# LUNA-CORE-02 evidence — file and runtime contract

Date: 2026-10-19
Status: PASS for source-level contract audit on Windows; no build, ABI, runtime, PDF or print acceptance claim.

## Deliverables

- `docs/协议/Core三端文件与运行时合同.md` explains Word/Slide/Sheet contracts, strict image error propagation, ABI preservation, SDKJS and WASM ownership, profile layers, and the compatibility boundary.
- `docs/协议/core-feature-contract.json` is the machine-readable contract, with the pinned Core baseline, reserved Word tags 200–209, existing property mappings, source anchors, strict image result codes and the complete eight-row Core/Browser SDKJS/Native SDKJS matrix.
- `docs/协议/feature-profile.schema.json` defines versioned source/dev/runtime profile shape. The current runner only accepts source profiles; later cards must add dev/runtime execution support.
- `scripts/core_features.py` registers the `contract` source case. The Windows source profile pins both contract files by SHA-256. The card changes documentation/profile/test code only; production Core files are unchanged.

## Verification

- `python -m unittest discover -s tests/core-features -p 'test_*.py' -v` passed (9 tests).
- `python scripts/core_features.py --case contract --platform windows-amd64 --profile tests/core-features/profiles/source-windows.json` passed with 64 assertions, including source anchor scans against the pinned Core checkout.
- `python scripts/core_features.py --case baseline --platform windows-amd64 --profile tests/core-features/profiles/source-windows.json --timeout 120` passed with 16 assertions.
- `python scripts/core_features.py --case fixtures --platform windows-amd64 --profile tests/core-features/profiles/source-windows.json --timeout 120` passed with 168 assertions.
- `git diff --check` passed. No Core source files or feature patches were changed by this card.

## Boundary

The tag allocation remains a proposed private encoding contract pending upgrade collision scan and C++ implementation. Contract checks establish consistency with the current pinned source, not functional serialization, ABI compatibility, compilation, SDKJS loading, or output correctness. Those require later build/runtime cards and Windows CI evidence.
