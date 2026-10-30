"""Linux snapshot contracts; disk schema captured on Windows, path adapted explicitly."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import ci_linux_compiler_cache as cache
import ci_linux_cache_validation as validation

class CacheTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.addCleanup(patch.stopall);patch.object(cache,'ROOT',self.root).start()
        patch.dict(os.environ,{'X2T_TARGET':'linux_64','X2T_DEPS_ID':'deps1','X2T_CORE_ID':'core1',
            'GITHUB_RUN_ID':'100','GITHUB_RUN_ATTEMPT':'1','GITHUB_JOB':'build','GITHUB_SHA':'source1',
            'X2T_SCCACHE':'/tmp/sccache','SCCACHE_DIR':'/tmp/linux-cache'},clear=True).start()
        (self.root/'config').mkdir();(self.root/'config/build-acceleration.json').write_text('{"sccacheVersion":"0.18.0"}')
        self.inputs={'platform':'linux_64','depsId':'deps1','compilerVersion':'locked-linux-sysroot',
            'gitObjects':{'ci/toolchains':'tool1','vendor/checksums.json':'locks1','vendor/detected-deps.json':'deps1','core':'source1'}}
        self.write_inputs();self.snap=self.root/'snapshot';(self.snap/'cache').mkdir(parents=True)
        os.environ['X2T_COMPILER_SNAPSHOT']=str(self.snap)
    def write_inputs(self):
        cache.write_json(self.root/'dist/core-inputs-linux_64.json',{'inputs':self.inputs})
    def raw(self):
        raw=json.loads((ROOT/'tests/core-features/fixtures/sccache-0.18.0-windows-disk.json').read_text())
        # Real 0.18 engine schema, only OS path adapted; NOT captured Linux disk evidence.
        raw['stats']['multi_level'][0]['location']='Local disk: "/tmp/linux-cache"'
        return raw
    def test_real_disk_schema_with_linux_path(self):
        self.assertEqual(cache.validate_stats(self.raw()),{'requests':4469,'hits':4469,'misses':0})
    def test_real_linux_gha_rejected(self):
        raw=json.loads((ROOT/'tests/core-features/fixtures/sccache-0.18.0-linux-gha.json').read_text())
        with self.assertRaises(ValueError):cache.validate_stats(raw)
    def test_strict_errors(self):
        for key in ('cache_read_errors','cache_write_errors','cache_timeouts','compile_fails','requests_not_cacheable','requests_unsupported_compiler','non_cacheable_compilations'):
            raw=self.raw();raw['stats'][key]=1
            with self.subTest(key=key),self.assertRaises(ValueError):cache.validate_stats(raw)
        raw=self.raw();raw['stats']['cache_errors']={'counts':{'C/C++':1}}
        with self.assertRaises(ValueError):cache.validate_stats(raw)
    def test_backend_and_linux_case_sensitive_path(self):
        for name in ('disk','L0 (ghac)','L1 (disk)'):
            raw=self.raw();raw['stats']['multi_level'][0]['name']=name
            with self.assertRaises(ValueError):cache.validate_stats(raw)
        with patch.dict(os.environ,SCCACHE_DIR='/tmp/Linux-cache'),self.assertRaises(ValueError):cache.validate_stats(self.raw())
        raw=self.raw();raw['stats']['multi_level'][0]['write_failures']=1
        with self.assertRaises(ValueError):cache.validate_stats(raw)
    def test_zero_preflight(self):
        raw=self.raw();raw['stats'].update(compile_requests=0,cache_hits={'counts':{}},cache_misses={'counts':{}},cache_writes=0)
        with patch.object(cache.subprocess,'check_output',return_value=json.dumps(raw)):cache.preflight()
        with self.assertRaises(ValueError):cache.validate_stats(raw)
        with patch.object(cache.subprocess,'check_output',return_value=json.dumps(self.raw())),self.assertRaises(ValueError):cache.preflight()
    def test_source_retains_prefix_toolchain_invalidates(self):
        prefix,key=cache.identities();os.environ.update(X2T_CORE_ID='core2',GITHUB_SHA='source2')
        self.inputs['gitObjects']['core']='source2';self.write_inputs()
        self.assertEqual(prefix,cache.identities()[0]);self.assertNotEqual(key,cache.identities()[1])
        self.inputs['gitObjects']['ci/toolchains']='tool2';self.write_inputs()
        self.assertNotEqual(prefix,cache.identities()[0])
    def test_arch_and_version_invalidate(self):
        prefix=cache.identities()[0]
        self.inputs['platform']='linux_arm64';cache.write_json(self.root/'dist/core-inputs-linux_arm64.json',{'inputs':self.inputs})
        with patch.dict(os.environ,X2T_TARGET='linux_arm64'):self.assertNotEqual(prefix,cache.identities()[0])
        (self.root/'config/build-acceleration.json').write_text('{"sccacheVersion":"0.19.0"}')
        self.assertNotEqual(prefix,cache.identities()[0])
    def test_pch_default_required(self):
        with patch.dict(os.environ,X2T_PCH_MODE='disabled'),self.assertRaises(ValueError):cache.identities()
    def test_cold_and_fallback_restore(self):
        cache.restored();self.assertEqual(json.loads(cache.diagnostic('compiler-cache-restore').read_text())['status'],'cold')
        (self.snap/'cache/object').write_bytes(b'object');cache.create_manifest(self.snap)
        old=cache.identities()[1];os.environ.update(GITHUB_RUN_ID='101',X2T_COMPILER_CACHE_MATCHED_KEY=old)
        cache.restored();self.assertEqual(json.loads(cache.diagnostic('compiler-cache-restore').read_text())['key'],old)
    def test_unknown_or_modified_bytes_rejected(self):
        obj=self.snap/'cache/object';obj.write_bytes(b'object')
        with self.assertRaises(ValueError):cache.restored()
        cache.create_manifest(self.snap);os.environ['X2T_COMPILER_CACHE_MATCHED_KEY']=cache.identities()[1];obj.write_bytes(b'changed')
        with self.assertRaises(ValueError):cache.restored()
    def test_snapshot_root_unknown_file_rejected(self):
        (self.snap/'unexpected').write_text('unknown')
        with self.assertRaises(ValueError):cache.restored()
    def test_manifest_count_tampering_rejected(self):
        (self.snap/'cache/object').write_bytes(b'object');cache.create_manifest(self.snap)
        manifest=json.loads((self.snap/'manifest.json').read_text());manifest['fileCount']=99
        cache.write_json(self.snap/'manifest.json',manifest)
        os.environ['X2T_COMPILER_CACHE_MATCHED_KEY']=cache.identities()[1]
        with self.assertRaises(ValueError):cache.restored()
    def test_cache_root_symlink_rejected(self):
        (self.snap/'cache').rmdir();(self.snap/'cache').symlink_to(self.root)
        with self.assertRaises(ValueError):cache.restored()
    def test_live_probe_gates_long_matrix(self):
        wrapper=(ROOT/'.github/workflows/linux-cache-validation.yml').read_text()
        self.assertIn('needs: [plan, disk-probe]',wrapper)
        self.assertIn('python3 scripts/ci_linux_cache_probe.py',wrapper)
        self.assertIn('branches: [main]',wrapper)
        self.assertIn('paths: [.github/workflows/linux-cache-validation.yml]',wrapper)
    def test_symlink_rejected(self):
        (self.snap/'cache/link').symlink_to(self.root)
        with self.assertRaises(ValueError):cache.inventory(self.snap/'cache')
    def test_absent_daemon_safe(self):
        with patch.object(cache,'daemon_pids',return_value=[]),patch.object(cache.subprocess,'run') as run:
            cache.stop_server();run.assert_not_called()
    def test_daemon_stop_waits_for_exit(self):
        with patch.object(cache,'daemon_pids',side_effect=[[1],[1],[]]),patch.object(cache.subprocess,'run') as run,patch.object(cache.time,'sleep'):
            cache.stop_server();run.assert_called_once_with(['/tmp/sccache','--stop-server'],check=True)
    def test_finish_success_after_stop(self):
        cache.write_json(cache.diagnostic('build-metrics'),{'exitCode':0,'pchMode':'default'})
        with patch.object(cache.subprocess,'check_output',return_value=json.dumps(self.raw())),patch.object(cache,'stop_server') as stop:
            cache.finish();stop.assert_called_once()
        self.assertTrue(json.loads(cache.diagnostic('compiler-cache-quality').read_text())['daemonStopped'])
    def test_finish_stop_error_no_receipt(self):
        cache.write_json(cache.diagnostic('build-metrics'),{'exitCode':0,'pchMode':'default'})
        with patch.object(cache.subprocess,'check_output',return_value=json.dumps(self.raw())),patch.object(cache,'stop_server',side_effect=RuntimeError('daemon alive')),self.assertRaises(RuntimeError):cache.finish()
        self.assertFalse(cache.diagnostic('compiler-cache-quality').exists())
    def test_finish_stats_error_still_stops(self):
        raw=self.raw();raw['stats']['cache_write_errors']=1
        with patch.object(cache.subprocess,'check_output',return_value=json.dumps(raw)),patch.object(cache,'stop_server') as stop,self.assertRaises(ValueError):cache.finish()
        stop.assert_called_once();self.assertFalse(cache.diagnostic('compiler-cache-quality').exists())
    def test_finish_waits_async_write(self):
        raw=self.raw();raw['stats'].update(compile_requests=1,cache_hits={'counts':{}},cache_misses={'counts':{'C/C++':1}},cache_writes=0)
        done=copy.deepcopy(raw);done['stats']['cache_writes']=1
        cache.write_json(cache.diagnostic('build-metrics'),{'exitCode':0,'pchMode':'default'})
        with patch.object(cache.subprocess,'check_output',side_effect=[json.dumps(raw),json.dumps(done)]),patch.object(cache,'stop_server'),patch.object(cache.time,'sleep') as sleep:
            cache.finish();sleep.assert_called_once()
    def test_pack_requires_stopped_quality(self):
        (self.snap/'cache/object').write_bytes(b'object')
        cache.write_json(cache.diagnostic('compiler-cache-quality'),{'status':'passed','daemonStopped':False})
        with self.assertRaises(ValueError):cache.pack()
    def test_save_exact_lookup_required(self):
        with self.assertRaises(ValueError):cache.saved()
        with patch.dict(os.environ,X2T_COMPILER_SAVED_KEY=cache.identities()[0]),self.assertRaises(ValueError):cache.saved()
        os.environ['X2T_COMPILER_SAVED_KEY']=cache.identities()[1];cache.saved()
    def evidence(self,reused=False):
        d=self.root/'evidence';d.mkdir()
        for n,v in {'core-reuse':{'coreId':'core1','reused':reused},'core-producer':{'coreId':'core1'},'build-metrics':{'exitCode':0}}.items():cache.write_json(d/f'{n}-linux_64.json',v)
        return d
    def test_binary_reuse_skip(self):
        d=self.evidence(True);self.assertEqual(validation.validate(d,'linux_64','reuse')['status'],'passed')
        with self.assertRaises(ValueError):validation.validate(d,'linux_64','cold')
    def test_warm_gate(self):
        d=self.evidence()
        for n,v in {'compiler-cache-quality':{'status':'passed','daemonStopped':True,'backend':'disk','requests':100,'hits':99,'misses':1},'compiler-cache-saved':{'status':'passed'},'compiler-cache-restore':{'status':'restored','coreId':'core1'}}.items():cache.write_json(d/f'{n}-linux_64.json',v)
        self.assertEqual(validation.validate(d,'linux_64','warm')['status'],'passed')
        with self.assertRaises(ValueError):validation.validate(d,'linux_64','reuse')
        cache.write_json(d/'compiler-cache-restore-linux_64.json',{'status':'cold'})
        with self.assertRaises(ValueError):validation.validate(d,'linux_64','warm')
    def test_workflow_guards(self):
        workflow=(ROOT/'.github/workflows/x2t-linux.yml').read_text()
        self.assertNotIn('SCCACHE_GHA',workflow);self.assertNotIn('IGNORE_SERVER_IO_ERROR',workflow)
        self.assertIn('lookup-only: true',workflow);self.assertIn('fail-on-cache-miss: true',workflow)
        self.assertLess(workflow.index('Flush and validate'),workflow.index('Save compiler snapshot'))
        self.assertIn("if: ${{ !inputs.rebuild_core }}",workflow)
        self.assertIn('SCCACHE_MULTILEVEL_CHAIN: disk',workflow)

if __name__=='__main__':unittest.main()
