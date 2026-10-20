# CORE-13 source receipt

2026-10-19. **PARTIAL — SOURCE-READY / WAIT-BUILD.** No C++ compilation, UNIT, DLL load, x2t or PDF execution. C++ assertions executed: 0.

- Commit: resolve `git log -1 -- patches/core/013-graphics-strict-image-errors.patch`. Dependencies: CORE-02 and BLD-01-FIX02 source contracts; BLD-02 and BLD-00-FIX01 remain actual build/runtime gates. This card does not depend on the unexecuted Word CODEC results.
- New isolated full staging started from the locked 21,117-file pristine Core source, with the previous four Word patches replayed. Neither original local `core/` nor any existing POC staging was edited.
- Adds fixed-width size/version policy/result PODs, a nonvirtual V1 graphics export and first-error reporting. Existing renderer/parameter struct layouts and virtual tables are unchanged. The old export remains and does not select strict image handling.
- The existing shared command interpreter is reused. In strict mode command111 fails on every non-S_OK (including S_FALSE), empty resolved path and resolver/draw exception, retaining command offset/type and renderer status. Image paths, clip/transform, PNG alpha, cache and existing resource resolver are not replaced. Legacy drawing exceptions/non-S_OK remain tolerated; legacy resolver exception placement is preserved.
- Primitive reader boundary/skip/string checks use existing fields, with no layout change; V1 translates malformed/truncated input and other exceptions to code2. Known length-prefixed records check their declared extent before pointer arithmetic. This does not prove comprehensive malformed advanced-command or resource-exhaustion safety; those are pending actual C++ tests. Previously undefined legacy out-of-bounds reads now throw instead of silently accessing past the buffer.
- Candidate order/hash, actual `git apply --check`/apply commands with `--whitespace=error-all`, exit codes and replay output hashes: `source-replay.json`. All five candidate patches replayed in order against fresh pristine copies; 15 source files were compared to development staging after newline normalization including BOM. These are source checks, not UNIT assertions.
- Explicit V1 interface and pending downstream parameter contract: `docs/协议/Core严格图片策略V1_候选合同.md`. Default baseline/series, source profile, V8/vendor lock and workflows retain their captured hashes. No download/prepare, Actions trigger, push, publish or deployment.

## Pending acceptance

`acceptance.json` is an unexecuted real-Core test matrix. Future `image-render` must compile the current graphics interpreter with real C++ renderer stubs/working target and invoke the actual old/V1 exports; do not implement the image-result algorithm in a Python test. Full-chain PDF tests remain downstream. Original card stays PARTIAL until its component tests really execute.
