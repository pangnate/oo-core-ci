"""Contracts for production disk compiler snapshots, separate from binary reuse."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import ci_windows_compiler_cache as cache

ENV = {'X2T_COMPILER_VERSION':'msvc-14.29.30133','X2T_DEPS_ID':'deps1','X2T_PCH_MODE':'disabled',
       'X2T_CORE_ID':'core1','GITHUB_RUN_ID':'100','GITHUB_RUN_ATTEMPT':'1','GITHUB_JOB':'build',
       'GITHUB_SHA':'source1','ImageVersion':'image1',
       'SCCACHE_DIR':r'D:\a\_temp\x2t-compiler-snapshot\cache'}

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); (self.root/'config').mkdir()
        (self.root/'config/build-acceleration.json').write_text('{"sccacheVersion":"0.18.0"}')
        self.addCleanup(patch.stopall)
        patch.object(cache,'ROOT',self.root).start()
        patch.dict(os.environ,ENV,clear=True).start()
        self.snap=self.root/'snapshot'; (self.snap/'cache').mkdir(parents=True)
        os.environ['X2T_COMPILER_SNAPSHOT']=str(self.snap)
        self.obj=self.snap/'cache/abc';self.obj.write_bytes(b'compiler object')

    def raw(self):
        # Captured from run 41016385724, job 123934492712, artifact 12961205790.
        raw=json.loads((ROOT/'tests/core-features/fixtures/sccache-0.18.0-windows-disk.json').read_text())
        raw['stats'].update(compile_requests=3, cache_hits={'counts':{'C/C++':2}},
                            cache_misses={'counts':{'C/C++':1}}, cache_writes=1)
        return raw

    def test_actual_production_stats_fixture(self):
        raw=json.loads((ROOT/'tests/core-features/fixtures/sccache-0.18.0-windows-disk.json').read_text())
        self.assertEqual(cache.validate_stats(raw), {'requests':4469,'hits':4469,'misses':0})

    def test_preflight_zero_requests_only(self):
        raw=self.raw()
        raw['stats'].update(compile_requests=0, cache_hits={'counts':{}}, cache_misses={'counts':{}}, cache_writes=0)
        self.assertEqual(cache.validate_stats(raw,preflight=True), {'requests':0,'hits':0,'misses':0})
        with self.assertRaises(ValueError):cache.validate_stats(raw)
        os.environ['X2T_SCCACHE']='sccache'
        with patch.object(cache.subprocess,'check_output',return_value=json.dumps(raw)):cache.preflight()
        self.assertTrue((self.root/'dist/sccache-preflight-win_64.json').exists())
        with patch.object(cache.subprocess,'check_output',return_value=json.dumps(self.raw())),self.assertRaises(ValueError):cache.preflight()

    def test_preflight_rejects_wrong_backend_and_errors(self):
        for name in ('disk','L0 (ghac)','L0 (disk-like)','L1 (disk)',''):
            raw=self.raw();raw['stats']['multi_level'][0]['name']=name
            with self.assertRaises(ValueError):cache.validate_stats(raw,preflight=True)
        for field,value in [('cache_location','Local disk'),('version','0.19.0')]:
            raw=self.raw();raw[field]=value
            with self.assertRaises(ValueError):cache.validate_stats(raw,preflight=True)
        with patch.dict(os.environ,SCCACHE_DIR=r'D:\other'),self.assertRaisesRegex(ValueError,'location'):
            cache.validate_stats(self.raw(),preflight=True)
        raw=self.raw();raw['stats']['multi_level'][0]['location']='ghac://other'
        with self.assertRaises(ValueError):cache.validate_stats(raw,preflight=True)

    def test_source_change_keeps_prefix_but_changes_snapshot_key(self):
        before=cache.identities()
        os.environ.update(X2T_CORE_ID='core2',GITHUB_SHA='source2')
        after=cache.identities()
        self.assertEqual(before[0],after[0]);self.assertNotEqual(before[1],after[1])

    def test_compatibility_changes_prefix(self):
        prefix=cache.identities()[0]
        for key,value in [('X2T_DEPS_ID','deps2'),('X2T_COMPILER_VERSION','msvc-other')]:
            with patch.dict(os.environ,{key:value}):self.assertNotEqual(prefix,cache.identities()[0])
        (self.root/'config/build-acceleration.json').write_text('{"sccacheVersion":"0.19.0"}')
        self.assertNotEqual(prefix,cache.identities()[0])

    def test_pch_not_disabled_rejected(self):
        for mode in ('default',''):
            with patch.dict(os.environ,X2T_PCH_MODE=mode),self.assertRaises(ValueError):cache.identities()

    def test_unique_run_attempt_and_job(self):
        key=cache.identities()[1]
        for name,value in [('GITHUB_RUN_ID','101'),('GITHUB_RUN_ATTEMPT','2'),('GITHUB_JOB','seed')]:
            with patch.dict(os.environ,{name:value}):self.assertNotEqual(key,cache.identities()[1])

    def test_invalid_identity_rejected(self):
        with patch.dict(os.environ,GITHUB_JOB='../bad'),self.assertRaises(ValueError):cache.identities()

    def test_manifest_roundtrip_and_producer_identity(self):
        saved=cache.create_manifest(self.snap)
        self.assertEqual(cache.verify_snapshot(self.snap,cache.compatibility()),saved)
        self.assertEqual(saved['producerSourceSha'],'source1')

    def test_modified_cache_bytes_rejected(self):
        cache.create_manifest(self.snap);self.obj.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'content'):cache.verify_snapshot(self.snap,cache.compatibility())

    def test_incompatible_manifest_rejected(self):
        cache.create_manifest(self.snap)
        with patch.dict(os.environ,X2T_DEPS_ID='other'),self.assertRaisesRegex(ValueError,'Incompatible'):
            cache.verify_snapshot(self.snap,cache.compatibility())

    def test_fallback_restore_keeps_old_producer_and_checks_key(self):
        saved=cache.create_manifest(self.snap)
        os.environ.update(GITHUB_SHA='source2',X2T_CORE_ID='core2',X2T_COMPILER_CACHE_MATCHED_KEY=saved['cacheKey'])
        cache.restored()
        receipt=json.loads((self.root/'dist/compiler-cache-restore-win_64.json').read_text())
        self.assertEqual(receipt['producerSourceSha'],'source1')
        with patch.dict(os.environ,X2T_COMPILER_CACHE_MATCHED_KEY=cache.identities()[1]),self.assertRaisesRegex(ValueError,'manifest key'):
            cache.restored()

    def test_unidentified_cold_bytes_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unidentified'):cache.restored()

    def test_clean_cold_destination_accepted(self):
        self.obj.unlink();cache.restored()
        self.assertEqual(json.loads((self.root/'dist/compiler-cache-restore-win_64.json').read_text())['status'],'cold')

    def test_pack_requires_quality(self):
        with self.assertRaises(FileNotFoundError):cache.pack()
        cache.write_json(self.root/'dist/compiler-cache-quality-win_64.json',{'status':'failed'})
        with self.assertRaises(ValueError):cache.pack()
        cache.write_json(self.root/'dist/compiler-cache-quality-win_64.json',{'status':'passed','daemonStopped':True})
        cache.pack();self.assertTrue((self.snap/'manifest.json').is_file())

    def test_all_cache_errors_rejected(self):
        for key in ('cache_read_errors','cache_write_errors','cache_timeouts','compile_fails',
                    'requests_not_cacheable','requests_unsupported_compiler'):
            raw=self.raw();raw['stats'][key]=1
            with self.assertRaises(ValueError,msg=key):cache.validate_stats(raw)
        raw=self.raw();raw['stats']['cache_errors']['counts']['C/C++']=1
        with self.assertRaises(ValueError):cache.validate_stats(raw)
        raw=self.raw();raw['stats']['multi_level'][0]['write_failures']=1
        with self.assertRaises(ValueError):cache.validate_stats(raw)

    def test_disk_backend_and_version_required(self):
        for levels in ([],[{'name':'ghac'}],[{'name':'disk'},{'name':'ghac'}]):
            raw=self.raw();raw['stats']['multi_level']=levels
            with self.assertRaises(ValueError):cache.validate_stats(raw)
        raw=self.raw();raw['version']='other'
        with self.assertRaises(ValueError):cache.validate_stats(raw)

    def test_real_requests_required_not_fixed_source_count(self):
        self.assertEqual(cache.validate_stats(self.raw()),{'requests':3,'hits':2,'misses':1})
        raw=self.raw();raw['stats']['compile_requests']=0
        with self.assertRaises(ValueError):cache.validate_stats(raw)
        raw=self.raw();raw['stats']['compile_requests']=4
        with self.assertRaises(ValueError):cache.validate_stats(raw)

    def test_successful_flush_waits_for_async_write_and_stops_daemon(self):
        cache.write_json(self.root/'dist/build-metrics-win_64.json',{'exitCode':0,'pchMode':'disabled'})
        pending=self.raw();pending['stats']['cache_writes']=0
        outputs=[json.dumps(pending),json.dumps(self.raw()),'INFO: No tasks']
        with patch.object(cache.subprocess,'check_output',side_effect=outputs),patch.object(cache.subprocess,'run') as stop,patch.object(cache.time,'sleep'):
            os.environ['X2T_SCCACHE']='sccache';cache.finish()
            stop.assert_called_once_with(['sccache','--stop-server'],check=True)
        self.assertEqual(json.loads((self.root/'dist/compiler-cache-quality-win_64.json').read_text())['status'],'passed')

    def test_error_flush_never_writes_success_but_stops_daemon(self):
        raw=self.raw();raw['stats']['cache_write_errors']=1
        with patch.object(cache.subprocess,'check_output',side_effect=[json.dumps(raw),'INFO: No tasks']),patch.object(cache.subprocess,'run') as stop:
            os.environ['X2T_SCCACHE']='sccache'
            with self.assertRaises(ValueError):cache.finish()
            stop.assert_called_once()
        self.assertFalse((self.root/'dist/compiler-cache-quality-win_64.json').exists())

    def test_stop_failure_cannot_produce_packable_quality_receipt(self):
        import subprocess
        cache.write_json(self.root/'dist/build-metrics-win_64.json',{'exitCode':0,'pchMode':'disabled'})
        with patch.object(cache.subprocess,'check_output',return_value=json.dumps(self.raw())),patch.object(cache.subprocess,'run',side_effect=subprocess.CalledProcessError(1,'stop')):
            os.environ['X2T_SCCACHE']='sccache'
            with self.assertRaises(subprocess.CalledProcessError):cache.finish()
        self.assertFalse((self.root/'dist/compiler-cache-quality-win_64.json').exists())

    def test_seed_import_preserves_original_source_and_checks_environment(self):
        entries=cache.inventory(self.snap/'cache')
        receipt={'files':entries,'inventorySha256':cache.digest(entries),'depsId':'deps1',
                 'compilerVersion':ENV['X2T_COMPILER_VERSION'],'sccacheVersion':'0.18.0','imageVersion':'image1',
                 'actualSourceSha':'original','cacheKey':'original-key'}
        inv=self.root/'old-inventory.json';inv.write_text(json.dumps(receipt))
        dest=self.root/'import';(dest/'cache').mkdir(parents=True)
        os.environ['X2T_COMPILER_SNAPSHOT']=str(dest)
        cache.import_seed(self.snap/'cache',inv)
        manifest=json.loads((dest/'manifest.json').read_text())
        self.assertEqual(manifest['producerSourceSha'],'original')
        self.assertNotIn('coreId',manifest)
        self.assertEqual(manifest['importTargetCoreId'],'core1')
        self.assertEqual(manifest['importedFrom']['cacheKey'],'original-key')
        receipt['depsId']='wrong';inv.write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):cache.import_seed(self.snap/'cache',inv)

class WorkflowTests(unittest.TestCase):
    def test_windows_workflow_real_rebuild_and_binary_fast_path(self):
        text=(ROOT/'.github/workflows/x2t-windows.yml').read_text()
        self.assertIn('if: ${{ !inputs.rebuild_core }}',text)
        self.assertNotIn('SCCACHE_IGNORE_SERVER_IO_ERROR',text)
        self.assertNotIn('SCCACHE_GHA_VERSION',text)
        self.assertIn("SCCACHE_GHA_ENABLED: 'false'",text)
        self.assertIn('SCCACHE_MULTILEVEL_CHAIN: disk',text)
        self.assertIn('X2T_PCH_MODE: disabled',text)
        self.assertIn('disable_annotations: true',text)
        self.assertLess(text.index('ci_windows_compiler_cache.py preflight'),text.index('      - name: Build X2T'))
        self.assertIn('restore-keys: ${{ env.X2T_COMPILER_CACHE_PREFIX }}',text)
        self.assertNotIn("steps.compiler-cache.outputs.cache-hit",text)
        self.assertIn('ci_core_cache.py check',text)
        self.assertIn('smoke_x2t_runtime.py',text)
        self.assertIn('package_windows.ps1',text)
        self.assertNotIn('41009631842',text)
        self.assertNotIn('a3affdf',text)

    def test_snapshot_save_requires_durable_exact_key_lookup(self):
        text=(ROOT/'.github/workflows/x2t-windows.yml').read_text()
        self.assertIn('id: saved-compiler-cache',text)
        self.assertIn('lookup-only: true',text)
        self.assertIn('fail-on-cache-miss: true',text)
        self.assertIn('steps.saved-compiler-cache.outputs.cache-matched-key',text)
        block=text.split('name: Confirm new compiler snapshot is durably available',1)[1].split('      - name:',1)[0]
        self.assertNotIn('restore-keys:',block)
        wrapper=(ROOT/'.github/workflows/validate-windows-production-cache.yml').read_text()
        self.assertIn('id: saved-seed',wrapper)
        self.assertIn('steps.saved-seed.outputs.cache-matched-key',wrapper)
        self.assertIn("if: github.event_name == 'workflow_dispatch' && inputs.run_linux",wrapper)
        self.assertIn('default: true',wrapper)
        self.assertIn('${{ github.sha }}',wrapper)
        self.assertIn('arch: [amd64, arm64]',wrapper)
        self.assertIn('uses: ./.github/workflows/x2t-linux.yml',wrapper)

    def test_validation_wrapper_distinguishes_forced_and_binary_reuse(self):
        wrapper=(ROOT/'.github/workflows/validate-windows-production-cache.yml').read_text()
        flag="rebuild_core: ${{ github.event_name == 'workflow_dispatch' && inputs.rebuild_core }}"
        self.assertEqual(wrapper.count(flag),2)
        self.assertIn('default: false',wrapper)
        self.assertIn('if: github.event_name != \'workflow_dispatch\' || !inputs.rebuild_core',wrapper)
        self.assertIn('needs: windows',wrapper)
        self.assertIn("assert reuse['reused'] is True",wrapper)
        self.assertIn("assert reuse['sourceSha'] == os.environ['GITHUB_SHA']",wrapper)
        self.assertIn("assert str(reuse['producerRunId']) != os.environ['GITHUB_RUN_ID']",wrapper)
        self.assertIn('name: x2t-windows-build-diagnostics',wrapper)

    def test_snapshot_steps_are_skipped_for_binary_hit(self):
        text=(ROOT/'.github/workflows/x2t-windows.yml').read_text()
        names={'Configure compatible compiler snapshot','Restore compatible compiler snapshot',
               'Verify restored compiler snapshot','Set up pinned compiler cache','Reset compiler cache counters','Validate compiler backend before compilation',
               'Record stopped compiler snapshot','Save compiler snapshot for subsequent source builds',
               'Confirm new compiler snapshot is durably available','Require exact saved compiler snapshot identity'}
        blocks=text.split('      - name: ')[1:]
        for name in names:
            block=next(x for x in blocks if x.splitlines()[0]==name)
            self.assertIn("if: steps.core-cache.outputs.cache-hit != 'true'",block)
        flush=next(x for x in blocks if x.splitlines()[0]=='Flush and strictly validate compiler cache')
        self.assertIn("steps.compile.outcome == 'success'",flush)
        self.assertIn("steps.compile.outcome == 'failure'",flush)

if __name__=='__main__':unittest.main()
