# CORE-15 source receipt

2026-10-19. **PARTIAL — SOURCE-READY / WAIT-BUILD.** No real C++ compilation, UNIT, executable/DLL load, x2t conversion, SDKJS or PDF/print acceptance. C++ assertions executed: 0.

- Commit: resolve `git log -1 -- patches/core/015-x2t-strict-image-policy.patch`. Source dependency CORE-14 `b4ddd5c7`, following CORE-13 `b9c3d1fb`. Actual 14 UNIT and matching Core 10 SDK/runtime remain pending.
- Three production files in patch015: cextracttools.h (task parameter), pdf_image.h (actual shared PDF branches), ASCConverters.cpp (root validation). No Worker, HTTP, MQ, database, Space or SDKJS production changes. TaskQueue remains the existing XML transport.
- XML `m_sImageFailurePolicyV1`: absent/legacy/0 uses the old tolerant entry, strict/1 selects PdfFile V1. Empty, other values and duplicates in one FromXmlNode parse return false; the existing CLI and exported FromXml map false to CONVERT_PARAMS. Existing file XML then explicit override XML is retained: a subsequent parse may override the prior valid policy. A direct C++ caller's invalid value is also rejected before dispatch and before either shared PDF branch allocates its conversion resources.
- Root dispatch rejects strict for unconnected conversion directions/targets instead of silently ignoring it. DOCX/XLSX/PPTX and editor binary/package routes targeting PDF/PDF-A pass through the shared doct_bin2pdf V1 choice. Raw binary/base64 PDF-command files use the shared bin2pdf choice. Existing direct/numbered formats and old calls remain. Static route tracing is not proof of execution.
- The strict helper initializes size/version/flags policy and result descriptors, catches C++ exceptions from the PdfFile call, emits only numeric code/command/offset/status diagnostics, and preserves the existing S_OK-only success comparisons. Nonzero V1 result code also forces failure even if HRESULT is S_OK. S_FALSE, failure HRESULT or exception map to the existing CONVERT error; image/decode/save failure returns before downstream signing. Signing's own existing output semantics are not redesigned.
- Production candidate hash/order, actual check/apply commands and replayed file hashes: `source-replay.json`. All seven candidates replayed against pristine copies of every touched file, with `--whitespace=error-all`; 15 files match development staging after newline normalization including BOM. This is source replay, not UNIT.
- `full-candidate-replay.json` records complete official-source staging (CI corrections → all seven candidates → branding), source/local-input before/after fingerprints and protected default POC input hashes. No existing Core or POC staging was used as a development directory. Default series/baseline/profile/V8 lock/vendor lock/workflows remain unchanged. No local C++ compile, Actions trigger, download/prepare, push, publish or deploy.
- Python infrastructure regression command: `python -m unittest discover -s tests/core-features -p 'test_*.py' -v`, exit0, **45 passed**. Those tests validate existing source infrastructure/default baseline and do not execute any new graphics/PdfFile/X2T C++ behavior. `git diff --check` for ordinary task files passes; raw patch context whitespace is checked as C++ additions by git apply instead.

## Reproduce source replay

Use the existing explicit opt-in wrapper with a new owned destination (never an existing POC tree):

```powershell
python tests/core-features/replay_candidate_source.py --series patches/core/series-word-candidate.json --source vendor/work/core-official-poc-20261019-01/unpacked/core-ed63e94de814ff1d4ea28cddfaba6939bc9df9ed --destination vendor/work/pdf-candidate-review-NEW
```

## Pending acceptance

`acceptance.json` is an unexecuted real C++ component matrix for `strict-entry`. Compile actual parameter/dispatch/exit handling and inject only external CPdfFile/renderer/filesystem outcomes. Check CLI process exit and exact file preservation, all three product routes plus binary/base64 raw commands, both tolerant and strict mode, S_FALSE and exceptions. Actual loaded DLL/SDK/JS/font hashes are NOT-RUN, not N/A or fake PASS. Full new-DLL/X2T linkage is CORE-16/19, actual Native PDF cases CORE-22～24; their gates remain closed.
