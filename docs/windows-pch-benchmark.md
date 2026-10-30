# Windows PCH compiler-cache experiment

This branch preserves the production default. `X2T_PCH_MODE=disabled` is accepted only for Windows builds with sccache enabled; it passes both `CONFIG+=disable_precompiled_header` and `CONFIG-=precompile_header` before qmake project evaluation. The mode is recorded in build metrics and the Core input identity. No shared verified Core binary cache is read or written by this experiment.

## Run

Push the experiment to `experiment/windows-pch-cache-20261030`, or dispatch **Compare Windows PCH compiler cache** on that branch. There is no publishing/deployment step. The workflow uses one dependency job and four Windows builds:

- default PCH: cold, then warm
- PCH disabled: cold, then warm

Each build starts on a fresh hosted Windows runner with a fresh checkout and checks for unexpected `.obj` or `.pch` files after preparation and before restoring third-party dependency objects. The single known iOS `TestDocs3_Prefix.pch` is source text, so only its exact path and pinned Git blob content are allowed (LF/CRLF checkout is normalized). Every other matching file still fails the check; an altered allowed source also fails. The check reports exact paths in `pch-freshness.json` and never deletes files. Both phases compile the complete target graph. Only compiler cache entries are shared, through a new GHA namespace bound to run ID, attempt and PCH mode. A cold run may still have hits from duplicate requests within that same build. Stop-server finishes before the matching warm run becomes eligible. Re-running an individual job is not a replacement for a full new comparison, since the run attempt changes the namespace.

Every successful phase checks PE architecture/dependencies, size limits, source-built module provenance and the existing DOCX/PPTX editor-BIN roundtrip smoke. These are not complete layout regression tests. Tested runtime folders and full diagnostic logs/JSON are uploaded with phase-specific names. Core packaging/branding is deliberately not changed.

## Read the result

`pch-benchmark-summary-<attempt>` contains JSON and Markdown. The comparison refuses to claim speedups if any phase is missing or failed, or if source SHA, dependency identity, runner image, compiler, CPU count, parallelism, compiler cache version or cache namespaces do not match. It reports overall build seconds and both all-request and cacheable-request hit rates; raw stage timings and resource samples remain in each phase artifact.

The disabled-PCH phase must have neither PCH compiler options in its build log nor PCH-related cache rejection counts. Cache errors, zero compile requests, zero warm-cache hits and failed smoke tests fail validation. A no-PCH cold run can be slower and can expose missing includes; such failure is an experimental result, not proof of regression in the default production build.

Hosted runner contention and cache/network service variation remain uncontrolled. One pair per mode is a diagnostic comparison, not a precise performance guarantee. The 170-minute per-build limit prevents an unexpectedly slow no-PCH build from running indefinitely.

## Local validation

`python -m unittest discover -s tests/core-features -p test_pch_benchmark.py -v`

`python -m unittest discover -s tests/core-features -p test_ci_core_cache.py -v`

These tests validate flag isolation, cache identity and reporting contracts without compiling native Core. Actual Windows compilation and smoke success must come from CI, not the Linux-side unit tests.
