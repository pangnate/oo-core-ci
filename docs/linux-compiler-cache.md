# Linux compiler-cache snapshots

Linux amd64 and arm64 use the existing Ubuntu 24.04 **host** jobs, with checksum-locked cross-sysroot toolchains. ARM64 is cross-compiled on x86_64. No Docker, compiler flags, C++ sources, PCH defaults, parallelism policy or Windows workflow/helper changes are included.

## Separate caches, separate guarantees

- The dependency handoff retains its existing exact dependency identity.
- The verified Core binary cache retains its exact CoreId and verification. `rebuild_core: true` bypasses only this cache; a normal binary miss still compiles.
- Compiler entries use sccache 0.18.0 with the explicit single `disk` backend. `actions/cache` transports a stopped snapshot. There is no per-object GHA backend or ignored I/O failure.
- Compatibility includes Linux target, dependency identity, locked toolchain/checksum/detection objects, sccache version, default PCH and schema. Source-only changes keep the prefix; sccache validates each compilation's actual inputs. Each save key includes CoreId, run, attempt and job to avoid immutable-key collisions.
- Restores verify manifest compatibility, matched key, all filenames, lengths and SHA-256 hashes. Unknown bytes and symlinks are rejected. A cold miss is valid.

Before compiling, zero-stats starts the daemon (fresh runners have none), then the helper requires the real 0.18 schema: `Multi-level (1 levels)` and exactly `L0 (disk)` at the configured Linux path, with zero counters. Linux paths are case-sensitive. The finish gate requires real cacheable requests and zero compilation, read, write, backend, timeout and non-cacheable errors. It waits for asynchronous writes, stops the daemon, and waits for the pinned process to exit before creating a success receipt or snapshot. Failure cleanup never creates a success receipt.

Save actions can warn rather than fail. An exact-key lookup-only restore with `fail-on-cache-miss`, followed by a matched-key assertion, is mandatory. Snapshot quality/saved/restore receipts and sccache JSON are uploaded as diagnostics. The cache is bounded at 8 GiB per architecture; GitHub repository quota and eviction can still cause cold builds. Unique snapshots consume space and old snapshots may be evicted. Cache visibility follows GitHub branch scope: main cannot restore an experimental feature-branch-only cache. Inactive entries can expire (normally after seven days); cache availability is not a performance guarantee.

## Staged main validation

`linux-cache-validation.yml` runs only on a main push changing **that wrapper file**, or manual dispatch. It calls the real reusable pipeline for both architectures, including existing ELF/identity verification and packaging. It does not create an independent fake compile path. Both architecture jobs first wait for a lightweight real native-host g++ probe using the pinned sccache action: isolated cold write, deletion/recompile, warm hit, identical object SHA-256, strict actual stats and stopped daemon. This probe is neither X2T compilation nor ARM runtime coverage.

1. Initial wrapper fallback `cold`: force compilation and require strict compiler-cache success plus confirmed save. It permits a valid compatible restore if one exists; the name is a rollout phase, not an assertion of a forced cache miss.
2. Change only the fallback to `warm` in a fresh main commit: force another real compilation; require restored bytes with the same CoreId and positive cache hits. Record exact hits/misses and investigate residual misses; do not assume a request or miss count.
3. Change only fallback to `reuse`: normal binary-cache lookup; the receipt job requires exact Core reuse and no compiler-cache quality receipt. This tests binary reuse, **not compiler speedup**.

Each phase is a fresh run to avoid upload-artifact name collisions on same-run reruns. Manual dispatch supports the same phase choices. Other Linux source/helper changes do not accidentally trigger the reuse-only assertion. The normal Build X2T workflow is unchanged.

Historical GHA baseline run 41016385724: amd64 compile 3532.876 s and full pipeline 66m36s; arm64 compile 3013.011 s and full pipeline 59m19s. Both had 18 hits / 4451 misses, with 133 / 149 cache write errors respectively. These are observed older-run timings, not controlled disk-cache comparisons or promises. New cold, independent warm and binary-reuse results must be reported separately, including transfer/dependency/verification/package costs. Existing amd64 verification includes ldd; ARM64 verification is ELF/identity/package inspection, **not ARM runtime execution**.

Tests use a captured Windows disk-engine JSON with explicitly adapted Linux path (not represented as captured Linux runtime evidence), plus actual Linux GHA JSON as a rejection fixture with namespace redacted. CI preflight verifies the actual Linux daemon before the long build. Run:

```sh
python3 -m unittest discover -s tests/core-features -p 'test_linux_compiler_cache.py'
```
