# Windows compiler cache

The daily `Build X2T` workflow still accepts `platform` and `rebuild_core`.
Only the Windows reusable workflow changes. Linux is unchanged.

- `rebuild_core: false` first tries the **exact verified Core binary cache**. A hit skips compiler-cache setup and compilation, then runs the existing verification and packaging stages. No fallback is permitted for binary artifacts.
- `rebuild_core: true` bypasses that binary shortcut but restores the **compiler snapshot**. Actual compiler requests still occur. sccache validates source, includes and compiler options per request; changed sources compile normally.
- Windows explicitly disables PCH. This improves compiler-cache coverage but can make an entirely cold build slower. The 12m19s experimental result was a warm build, not a cold-build promise or total workflow duration.

## Disk snapshots

sccache writes only local disk. `actions/cache` transfers one snapshot archive between runners, instead of writing each object through the GHA backend.

A compatibility prefix covers platform, dependency input ID, compiler version, sccache version, PCH mode and cache schema. It deliberately omits source identity so source edits can reuse unaffected entries. Exact snapshot keys additionally include Core input ID, workflow run, attempt and job. A restored fallback is always saved under the new unique key after successful compilation and validation.

The archive includes a producer/source receipt and a SHA-256 inventory of cached bytes. Restore rejects incompatible or modified snapshots. Compilation must produce real cacheable requests with zero read/write/backend/timeout errors. All asynchronous writes finish, then the daemon exits before the snapshot is saved. An exact-key lookup must confirm the snapshot is available; a warning-only cache-save failure cannot pass validation. `SCCACHE_IGNORE_SERVER_IO_ERROR` is not enabled. Cache failures remain visible.

Compiler snapshots are not verified runtime binaries. Existing Core producer checks, executable/DLL hashes, DOCX/PPTX smoke verification, branding and package receipts remain in place. Verified Core binary cache is saved only after the existing verification stage passes.

GitHub cache branch visibility still applies. A snapshot created on an experimental branch may not be visible from `main`; its first build can therefore be cold. The branch-only validation wrapper performs a one-time, content-verified import of the previously tested experiment snapshot to avoid repeating that cold build during this migration. The normal Windows workflow has no pinned old run, source or dependency ID.

The original PCH comparison workflow is now manually triggered only. `validate-windows-production-cache.yml` runs the actual Windows reusable workflow plus both Linux architectures on the experiment branch; it is not an automatic `main` build trigger.
