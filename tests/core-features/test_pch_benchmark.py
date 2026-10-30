"""Regression checks for opt-in PCH configuration and honest benchmark reporting."""
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
import build_x2t
import ci_core_cache
import pch_benchmark_report as report


class PchConfigurationTests(unittest.TestCase):
    def args(self, **kwargs):
        return build_x2t.qmake_arguments(Path('.'), Path('fixture.pro'), [], windows=True, cache=True, **kwargs)

    def test_default_preserves_pch(self):
        self.assertFalse(any('precompile' in value for value in self.args()))

    def test_opt_in_disables_pch_before_project_evaluation(self):
        args = self.args(pch_mode='disabled')
        self.assertIn('CONFIG+=disable_precompiled_header', args)
        self.assertIn('CONFIG-=precompile_header', args)
        self.assertNotIn('-after', args)

    def test_rejects_invalid_configuration(self):
        for mode in ('off', '0', ''):
            with self.assertRaises(ValueError):
                self.args(pch_mode=mode)
        for windows, cache in ((False, True), (True, False)):
            with self.assertRaises(ValueError):
                build_x2t.qmake_arguments(Path('.'), Path('x.pro'), [], windows=windows, cache=cache, pch_mode='disabled')

    def test_core_identity_tracks_pch_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'config').mkdir()
            (root / 'config/build-acceleration.json').write_text('{"parallelism":"cpu-count"}')
            with patch.object(ci_core_cache, 'ROOT', root), patch.object(ci_core_cache, 'INPUTS', ()), patch.dict(os.environ, {}, clear=True):
                baseline = ci_core_cache.identity('win_64', 'deps')['coreId']
                with patch.dict(os.environ, X2T_PCH_MODE='disabled'):
                    disabled = ci_core_cache.identity('win_64', 'deps')['coreId']
                self.assertNotEqual(baseline, disabled)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.metrics = {'exitCode': 0, 'pchMode': 'disabled', 'compilerCache': True}
        self.raw = {'stats': {'compile_requests': 10, 'cache_hits': {'counts': {'C/C++': 8}},
                             'cache_misses': {'counts': {'C/C++': 2}}, 'requests_not_cacheable': 0,
                             'not_cached': {}, 'cache_errors': {'counts': {}}}, 'version': '0.18.0'}
        self.smoke = {'status': 'passed'}

    def check(self, mode='disabled', phase='warm', log='sccache cl -c a.cpp'):
        return report.validate(self.metrics, self.raw, self.smoke, log, mode, phase)

    def test_valid_counts(self):
        self.assertEqual(self.check()['allRequestHitPercent'], 80)

    def test_full_request_denominator(self):
        self.metrics['pchMode'] = 'default'
        self.raw['stats'].update(compile_requests=20, requests_not_cacheable=10, not_cached={'-Fp': 10})
        result = self.check(mode='default', log='sccache cl -Fpheader.pch a.cpp')
        self.assertEqual(result['allRequestHitPercent'], 40)
        self.assertEqual(result['cacheableHitPercent'], 80)

    def test_pch_commands_or_rejections_reject_disabled_claim(self):
        for flag in ('-Fpfile.pch', '/Ycpre.h', '-Yupre.h'):
            with self.assertRaisesRegex(ValueError, 'actually disabled'):
                self.check(log='sccache cl '+flag+' a.cpp')
        self.raw['stats']['not_cached'] = {'-Fp': 1}
        with self.assertRaises(ValueError):
            self.check()

    def test_no_object_reuse_as_warm_result(self):
        self.raw['stats']['compile_requests'] = 0
        with self.assertRaises(ValueError):
            self.check()

    def test_cache_outage_not_silent_fallback(self):
        self.raw['stats']['cache_write_errors'] = 1
        with self.assertRaises(ValueError):
            self.check()

    def test_failed_smoke_not_success(self):
        self.smoke['status'] = 'failed'
        with self.assertRaises(ValueError):
            self.check()

    def test_zero_warm_hits_not_success(self):
        self.raw['stats']['cache_hits']['counts'] = {}
        with self.assertRaises(ValueError):
            self.check()

    def test_baseline_requires_real_pch_commands(self):
        self.metrics['pchMode'] = 'default'
        with self.assertRaises(ValueError):
            self.check(mode='default')


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.records = []
        for mode in report.MODES:
            for phase in report.PHASES:
                self.records.append({'status': 'passed', 'mode': mode, 'phase': phase, 'sourceSha': 'a',
                    'runId': '1', 'runAttempt': '1', 'depsId': 'deps', 'runner': {'ImageVersion': '1'},
                    'compilerVersion': '14.29', 'cpuCount': 4, 'jobs': 4, 'seconds': 100,
                    'cacheNamespace': 'bench-'+mode, 'cache': {'compilerCacheVersion': '0.18.0'}})

    def test_matching_results(self):
        self.assertEqual(report.compare_records(self.records)['status'], 'passed')

    def test_missing_or_duplicate_phase(self):
        for values in (self.records[:-1], self.records + [self.records[0]]):
            with self.assertRaises(ValueError):
                report.compare_records(values)

    def test_different_runner_does_not_claim_speedup(self):
        self.records[-1]['runner'] = {'ImageVersion': '2'}
        with self.assertRaisesRegex(ValueError, 'unmatched runner'):
            report.compare_records(self.records)

    def test_cache_namespaces(self):
        self.records[-1]['cacheNamespace'] = 'other'
        with self.assertRaises(ValueError):
            report.compare_records(self.records)

    def test_workflows_are_branch_scoped_and_fresh_runner_pairs(self):
        entry = (ROOT / '.github/workflows/compare-windows-pch.yml').read_text()
        job = (ROOT / '.github/workflows/x2t-pch-benchmark-job.yml').read_text()
        self.assertIn("branches: ['experiment/windows-pch-cache-20261030']", entry)
        for mode in report.MODES:
            self.assertIn('needs: [deps, '+mode+'_cold]', entry)
        self.assertIn('${{ github.run_id }}-${{ github.run_attempt }}-${{ inputs.mode }}', job)
        self.assertNotIn('SCCACHE_IGNORE_SERVER_IO_ERROR', job)
        self.assertNotIn('Restore verified Core cache', job)
        self.assertLess(job.index('Assert fresh Core object outputs'), job.index('Restore verified dependency handoff'))
        self.assertIn('--stop-server', job)
        self.assertIn('disable_annotations: true', job)
        self.assertIn('${{ inputs.mode }}-${{ inputs.phase }}-${{ github.run_attempt }}', job)
        self.assertIn('smoke_x2t_runtime.py', job)


if __name__ == '__main__':
    unittest.main()
