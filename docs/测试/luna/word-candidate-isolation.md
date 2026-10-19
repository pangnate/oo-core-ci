# Word source candidate isolation

2026-10-19. This is source-management/test maintenance, not another completed Core feature card.

Four candidate patches coexist with an empty enabled `patches/core/series.json`. Their only consumer is an explicitly supplied `patch_series` in a new isolated staging; default source profile, baseline, V8 lock and workflows are unchanged. The running POC keeps its original checkout/inputs; this work neither triggers nor pushes a run.

An initial `python -m unittest discover -s tests/core-features -p 'test_*.py' -v` returned exit 1 (43 pass, 1 fail): the old baseline test equated root-level patch files with enabled patches. `download.write_baseline` had the same discovery behavior. Both now read the default enabled series. The baseline test still requires both default series and baseline to have no enabled feature patches and checks their source identity. The downloader checks the active series schema/source/order/dependencies and each file SHA256 before writing the baseline; wrong source, missing or modified active files fail rather than silently dropping patches.

A temporary-repository regression test verifies unbuilt candidate files are excluded, explicit promotion preserves ordered paths, and drift/wrong-source errors do not replace the prior baseline. No production downloader operation was run against the user checkout.

After the correction, the same command returned exit 0: **45 tests passed**. These tests cover Python/source infrastructure and the existing baseline/fixture contracts; they do not compile or run the new Core C++ patches. `WORD SOURCE-READY` remains separate from C++ UNIT/CODEC acceptance.

Full official-source staging of the final candidate set and protected-input before/after hashes are recorded in `LUNA-CORE-07/full-candidate-replay.json`. Each card also records scoped feature-patch replay and its unexecuted real acceptance matrix.

Patch files contain unified-diff context (a leading space before upstream tabs and blank lines). A generic `git show --check` may flag that patch syntax. Check the resulting C++ additions with `git apply --check --whitespace=error-all`, and check ordinary edited files with `git diff --check`; do not rewrite context or claim that patch text warnings are a C++ compilation result.
