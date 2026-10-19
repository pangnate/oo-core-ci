# LUNA-CORE-00 evidence — Windows Core baseline and link closure

Date: 2026-10-19
Status: PASS for read-only source/dependency audit; no Core build or runtime-load claim.

## Scope and repository state

- Pinned Core baseline: `ed63e94de814ff1d4ea28cddfaba6939bc9df9ed` (`v10.0.0.169-2`); build_tools: `a9f9895b172b09595abcafe85d56fab163f9ecb7`.
- The official Core archive contains 21,117 files. Its canonical tree hash, using the locked algorithm `sha256(sorted UTF-8 path + NUL + raw file SHA256)`, is `ea6b4a04be6a1459caa1e9e23d3c59659a7c6cf65f39cb0222690602d2b77e34`; the stale lock value was corrected.
- `git diff -- core` is empty. No functional Core source was modified and no feature patch was created by this card. The baseline declares only `scripts/patch_x2t_sln.py` as a project build patch and `Common/copyright.txt` as a branding overlay.
- The Windows checkout uses CRLF. After line-ending normalization, the official archive differs in exactly three declared paths: `X2tConverter/build/Qt/X2tSLN.pri`, `X2tConverter/build/Qt/X2tConverter.pro` (existing X2T build patch), and `Common/copyright.txt` (branding overlay). There are no undeclared source differences.
- `python scripts/verify_vendor.py --platform windows` passed: `Vendor inputs OK (windows)`.

## Build and link closure inspected

- `X2tConverter/build/Qt/X2tSLN.pri` includes `BinDocument`; `X2tConverter.pri` links `BinDocument` and declares runtime dependencies including `graphics`, `PdfFile`, `doctrenderer`, and `DocxRenderer`.
- `BinDocument.pro` builds a static library. `graphics.pro` builds the graphics shared library and includes `TextShaper.cpp` and `MetafileToRenderer.cpp`.
- `doctrenderer.pri` exports `doctrenderer`, includes the text-shaper integration and `TextMeasurerEmbed.cpp`. `PdfFile.pro` builds the dynamic `PdfFile` library, depends on graphics, and its conversion path calls `OnlineOfficeBinToPdf`.
- The checked-in `core/Common/3dParty/v8_89` directory is only a placeholder; a complete V8 SDK is not present. In the current PowerShell session `qmake`, `cl`, `msbuild`, `ninja`, and `cmake` were not discoverable via `Get-Command` (this does not assert they are absent elsewhere on the machine). No compile was attempted.

## Windows runtime version audit

- `D:/ONLYOFFICE/onlyoffice-x2t-ci/native-bin/windows/bin` is **DocumentServer 9.4.0.129**, not the Core 10 baseline. It must not seed or satisfy a Core 10 build. Directory fingerprint: `af6450afe85cc7ce6e257c792c230bd9c937daedf04603d28bd5083f1f3fe587`.
- A separate locked candidate exists at `vendor/runtime/windows-amd64-runtime.zip`, SHA-256 `1d562e5f9481f862f174bbdd4f43251af0a1f8763d8e665fdaf20e9be1af4b48`. Its 19 DLLs match the separately configured product runtime directory byte-for-byte. The 17 Core DLL version resources report `10.0.0.169`; the two ICU DLLs report `74.2`.
- Candidate provenance metadata says `operator-manual-upgrade; metadata-only-reconciliation`. Version resources and matching bytes establish a reproducible candidate, but do not prove that it loads with this checkout or can convert documents. It is therefore not accepted as the runtime baseline until `LUNA-CORE-BLD-00-FIX01` performs actual load and ordinary DOCX/PPTX conversion smoke tests. If those fail, build the full pinned-Core-10 Windows DLL closure from source.
- The candidate DLL archive does not contain Native JS. The product source lock pins SDKJS commit `3a94485abd83b1683cf4e64aec229d46b89778bd`; its files are available in the product workspace and must be staged as a separate, source-locked input when the later runtime-integration card requires them.

## Acceptance boundary

Source identity, declared patch/overlay boundaries, Windows vendor inputs, and link-closure review passed. This card did not compile Core, load candidate DLLs, run X2T, or perform DOCX/PPTX/PDF/print acceptance. Those runtime claims remain owned by the Windows build and feature cards. No Linux build or remote CI was run.
