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

## Measured validation (2026-10-30)

Independent Actions runs used unchanged compilation inputs (same Core ID, dependency ID, compiler environment, source/patch/overlay and toolchain objects), four build workers, and default PCH. The runner identity recorded by all build producers was `ubuntu24 / 20261026.354.1`. The warm run forced a build, bypassing exact binary reuse, and restored the preceding cold run's verified disk snapshot.

The old GHA reference reported `use_preprocessor_cache_mode=false`; both disk compilation runs reported `true`. Timings therefore compare the complete cache configuration, not isolated HTTP-versus-disk latency. Compiler flags and PCH settings were unchanged.

| Phase / run | Architecture | Build script | Compile/link stage | deps start → package end | Cache hits / misses | Write errors |
|---|---|---:|---:|---:|---:|---:|
| [Old GHA reference](https://github.com/pangnate/oo-core-ci/actions/runs/41016385724) | amd64 | 58m53s | 58m40s | 66m36s | 18 / 4451 | 133 |
| Old GHA reference | arm64 | 50m13s | 50m02s | 59m19s | 18 / 4451 | 149 |
| [Disk cold](https://github.com/pangnate/oo-core-ci/actions/runs/41026250322) | amd64 | 34m09s | 34m01s | 39m47s | 0 / 4469 | 0 |
| Disk cold | arm64 | 34m51s | 34m43s | 41m52s | 0 / 4469 | 0 |
| [Disk forced warm](https://github.com/pangnate/oo-core-ci/actions/runs/41031410933) | amd64 | 6m27s | 6m17s | 11m51s | 4469 / 0 | 0 |
| Disk forced warm | arm64 | 8m48s | 8m36s | 13m19s | 4469 / 0 | 0 |
| [Exact binary reuse](https://github.com/pangnate/oo-core-ci/actions/runs/41033295925) | amd64 | Skipped | Skipped | 3m38s | Not run | Not run |
| Exact binary reuse | arm64 | Skipped | Skipped | 3m30s | Not run | Not run |

Warm build-script time was 81.1% lower on amd64 and 74.7% lower on arm64 than this disk-cold observation. These are single-run measurements, not guaranteed speedups; hosted-runner contention and artifact transfer variation affect elapsed times. The old GHA reference was near-cold, not an intentionally empty cache, and its overall workflow was red because of an unrelated Windows checker; both Linux chains succeeded.

| Phase | Architecture | deps | build job | verify | package | Job sum | Scheduling gaps |
|---|---|---:|---:|---:|---:|---:|---:|
| Old GHA reference | amd64 | 4m25s | 61m08s | 25s | 31s | 66m29s | 7s |
| Old GHA reference | arm64 | 6m03s | 52m06s | 36s | 27s | 59m12s | 7s |
| Disk cold | amd64 | 3m06s | 35m49s | 27s | 19s | 39m41s | 6s |
| Disk cold | arm64 | 4m16s | 36m37s | 34s | 19s | 41m46s | 6s |
| Disk forced warm | amd64 | 44s | 8m03s | 1m25s | 1m32s | 11m44s | 7s |
| Disk forced warm | arm64 | 45s | 10m43s | 54s | 50s | 13m12s | 7s |
| Exact binary reuse | amd64 | 43s | 58s | 1m04s | 45s | 3m30s | 8s |
| Exact binary reuse | arm64 | 42s | 1m01s | 56s | 44s | 3m23s | 7s |

Elapsed time covers each architecture's normal deps/build/verify/package chain; plan, native-g++ probe, and additional validation-receipt jobs are excluded. Build-script timing includes qmake plus the compile/link stage and small script overhead; build-job timing additionally includes setup, downloads, cache validation and uploads. The warm compile/link stage still includes preprocessing, linking and build orchestration even with 100% sccache request hits.

The cold and forced-warm runs reported one `L0 (disk)` backend, sccache 0.18.0, an 8 GiB limit, zero cache read/write errors, timeouts, compile failures and non-cacheable requests. Daemon-stop receipts passed before snapshot save; exact saved-key lookup receipts passed. Each warm restore matched the cold producer's Core ID and inventory digest. Snapshots contained 4,557 files: amd64 86,177,030 bytes and arm64 83,350,092 bytes (logical inventory sizes, not compressed upload sizes); warm inventories were unchanged.

The reuse run reported `reused=true` for both architectures, with the cold run as binary producer (the exact binary cache key was already populated). Actions explicitly skipped `Build X2T` and compiler-cache setup/restore/save steps. Its retained cold-producer metrics are historical metadata, **not new compilation time**. The table uses actual reuse-job timestamps.

Downloaded diagnostics and package artifact SHA-256 values matched GitHub metadata. All package SHA256SUMS entries, inner binary, producer and verification checksums agreed. Binary SHA-256 remained identical across the old GHA reference, disk cold, forced warm and exact reuse:

- amd64: `f9c987db72004fef02e1011fb93b99534818f140f7ccde4c1ed93dbe05c629e7`
- arm64: `afb5f2e54c8c7fb5431c26265b69c24dc8762ee77d5de4145da313ff45676a92`

This verifies build/package identity, not application-level conversion correctness: amd64 had ELF/ldd checks; arm64 was cross-compiled, not executed on ARM hardware. Snapshot availability remains subject to GitHub Actions cache expiration and quota eviction. Windows was not modified by this Linux optimization.
