# LUNA-CORE-BLD-00 Windows isolated development build channel

Status: **DONE**. Evidence records the isolated Windows build channel and its dependency probe only. This card does not claim a full `x2t.exe` build; that acceptance belongs to LUNA-CORE-BLD-00-FIX01.

## CI evidence

- Workflow run [#22](https://github.com/pangnate/onlyoffice-x2t-ci/actions/runs/39367100886) on `main`, commit `a85fbad8b851ab83bc7566c9030e8208ed52e721`: **success**.
- Windows Server 2022 validated the locked Core/SDK inputs, restored the fixed V8 SDK, assembled the Windows feature SDK, compiled and ran the native dependency probes, completed the isolated Qt qmake + nmake `dependency-probe`, and uploaded `windows-core-feature-sdk`.
- The `dependency-probe` source is `tests/core-features/cpp/build_deps_windows_probe.cpp`; it exercises the SDK dependency set. It is not the production X2T target and does not produce `x2t.exe`.

## Local checks

On the same commit:

- `python -m py_compile scripts/build_core_dev.py` — passed.
- `python tests/core-features/test_dev_build.py` — 4 tests passed.
- `git diff --check` — passed.

## Boundary

LUNA-CORE-BLD-00-FIX01 remains responsible for auditing/reusing the candidate Windows runtime only if it passes source, load, and ordinary DOCX/PPTX conversion checks; otherwise it must build the complete pinned Core 10 DLL closure and X2T. No full X2T build or conversion result is claimed by this evidence.
