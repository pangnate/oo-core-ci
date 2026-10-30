#!/usr/bin/env python3
"""Validate isolated PCH cold/warm evidence; never infer speedups from failed jobs."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MODES = ('default', 'disabled')
PHASES = ('cold', 'warm')


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def total(value) -> int:
    if isinstance(value, dict):
        return sum(total(v) for v in value.values())
    return int(value)


def validate(metrics: dict, raw: dict, smoke: dict, log: str, mode: str, phase: str) -> dict:
    if mode not in MODES or phase not in PHASES:
        raise ValueError('invalid benchmark mode/phase')
    if metrics.get('exitCode') != 0 or smoke.get('status') != 'passed':
        raise ValueError('build and runtime smoke must both pass')
    if metrics.get('pchMode') != mode or not metrics.get('compilerCache'):
        raise ValueError('build used different PCH/cache configuration')
    stats = raw['stats']
    requests = stats['compile_requests']
    hits = total(stats['cache_hits']['counts'])
    misses = total(stats['cache_misses']['counts'])
    if requests <= 0:
        raise ValueError('no compilation requests: object reuse is not a compiler-cache benchmark')
    for key in ('cache_read_errors', 'cache_write_errors', 'cache_timeouts', 'compile_fails'):
        if stats.get(key, 0):
            raise ValueError(f'compiler cache error: {key}={stats[key]}')
    if total(stats.get('cache_errors', {}).get('counts', {})):
        raise ValueError('compiler cache backend errors')
    pch_commands = sum(bool(re.search(r'(?:^|\s)[/-](?:Fp|Y[cu])\S*', line)) for line in log.splitlines())
    reasons = stats.get('not_cached', {})
    pch_rejections = sum(value for key, value in reasons.items() if key in ('-Fp', '/Fp', '-Yc', '/Yc', '-Yu', '/Yu'))
    if mode == 'disabled' and (pch_commands or pch_rejections):
        raise ValueError('PCH was not actually disabled in compiler commands/cache stats')
    if mode == 'default' and not pch_commands:
        raise ValueError('baseline has no PCH commands; comparison is not meaningful')
    if phase == 'warm' and hits <= 0:
        raise ValueError('warm run did not retrieve any cached compilations')
    return {'requests': requests, 'hits': hits, 'misses': misses,
            'notCacheable': stats['requests_not_cacheable'], 'notCachedReasons': reasons,
            'allRequestHitPercent': round(100 * hits / requests, 2),
            'cacheableHitPercent': round(100 * hits / (hits + misses), 2) if hits + misses else 0,
            'pchCommandCount': pch_commands, 'pchRejections': pch_rejections,
            'compilerCacheVersion': raw.get('version'), 'cacheLocation': raw.get('cache_location')}



# This is an Objective-C prefix-header source, not a compiled MSVC PCH.
# Pin its Git blob identity rather than exempting all tracked files or test trees.
SOURCE_PCH = {
    'Test/Applications/iosTest/TestDocs3/TestDocs3_Prefix.pch':
        'b6a1f78b1f0b80e7c9216d885c77047b0bd62701',
}


def fresh_object_evidence(core: Path) -> dict:
    if not core.is_dir():
        raise ValueError(f'Core source directory is missing: {core}')
    allowed, unexpected = [], []
    for path in sorted(core.rglob('*')):
        if path.suffix.lower() not in ('.obj', '.pch') or not path.is_file():
            continue
        relative = path.relative_to(core).as_posix()
        if relative in SOURCE_PCH and not path.is_symlink():
            # Windows text checkout may use CRLF; Git stores this source as LF.
            content = path.read_bytes().replace(b'\r\n', b'\n')
            blob = hashlib.sha1(b'blob ' + str(len(content)).encode('ascii') + b'\0' + content).hexdigest()
            if blob == SOURCE_PCH[relative]:
                allowed.append({'path': relative, 'gitBlobSha': blob, 'kind': 'source-prefix-header'})
                continue
        unexpected.append(relative)
    return {'status': 'passed' if not unexpected else 'failed',
            'allowedSourceHeaders': allowed, 'unexpectedObjectOrPchFiles': unexpected}


def check_fresh(core: Path, receipt: Path) -> None:
    evidence = fresh_object_evidence(core)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, indent=2))
    if evidence['status'] != 'passed':
        raise ValueError('Fresh Core contains unexpected object/PCH files: '
                         + ', '.join(evidence['unexpectedObjectOrPchFiles']))


def record(mode: str, phase: str) -> None:
    dist = ROOT / 'dist'
    metrics = read_json(dist / 'build-metrics-win_64.json')
    stats = read_json(dist / 'sccache-stats-win_64.json')
    smoke = read_json(ROOT / 'vendor/work/x2t-baseline-smoke-receipt.json')
    summary = validate(metrics, stats, smoke, (dist / 'build-win_64.log').read_text(encoding='utf-8'), mode, phase)
    inputs = read_json(dist / 'core-inputs-win_64.json')['inputs']
    result = {'status': 'passed', 'mode': mode, 'phase': phase, 'sourceSha': metrics['sourceSha'],
              'runId': os.environ['GITHUB_RUN_ID'], 'runAttempt': os.environ['GITHUB_RUN_ATTEMPT'],
              'cacheNamespace': os.environ['SCCACHE_GHA_VERSION'], 'depsId': inputs['depsId'],
              'runner': inputs['runner'], 'compilerVersion': inputs['compilerVersion'],
              'cpuCount': metrics['cpuCount'], 'jobs': metrics['jobs'],
              'seconds': metrics['seconds'], 'stages': metrics['stages'], 'cache': summary,
              'smokeAcceptance': smoke['acceptance']}
    (dist / 'pch-benchmark-result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


def compare_records(records: list[dict]) -> dict:
    pairs = {(r['mode'], r['phase']): r for r in records}
    expected = {(m, p) for m in MODES for p in PHASES}
    if len(pairs) != len(records) or set(pairs) != expected:
        raise ValueError('missing or duplicate successful phase records; no valid comparison')
    reference = pairs[('default', 'cold')]
    for r in records:
        if r.get('status') != 'passed':
            raise ValueError('failed phase cannot be compared')
        for key in ('sourceSha', 'runId', 'runAttempt', 'depsId', 'runner', 'compilerVersion', 'cpuCount', 'jobs'):
            if r[key] != reference[key]:
                raise ValueError(f'unmatched {key}; do not interpret timings as a PCH speedup')
        if r['cache']['compilerCacheVersion'] != reference['cache']['compilerCacheVersion']:
            raise ValueError('unmatched compiler cache version')
    for mode in MODES:
        if pairs[(mode, 'cold')]['cacheNamespace'] != pairs[(mode, 'warm')]['cacheNamespace']:
            raise ValueError('cold/warm pair did not share compiler cache namespace')
    if pairs[('default', 'cold')]['cacheNamespace'] == pairs[('disabled', 'cold')]['cacheNamespace']:
        raise ValueError('PCH variants must have isolated compiler cache namespaces')
    return {'status': 'passed', 'results': records, 'comparison': {
        phase: {'defaultSeconds': pairs[('default', phase)]['seconds'],
                'disabledSeconds': pairs[('disabled', phase)]['seconds'],
                'disabledVsDefaultRatio': round(pairs[('disabled', phase)]['seconds'] / pairs[('default', phase)]['seconds'], 4)}
        for phase in PHASES}, 'limits': 'One cold/warm pair per mode; shared hosted runner variance remains. Smoke is DOCX/PPTX roundtrip, not full layout regression.'}


def compare(root: Path) -> None:
    records = [read_json(p) for p in sorted(root.rglob('pch-benchmark-result.json'))]
    try:
        result = compare_records(records)
    except ValueError as error:
        result = {'status': 'incomplete-or-unmatched', 'reason': str(error), 'results': records}
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    (dist / 'pch-benchmark-summary.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    lines = ['# Windows PCH benchmark', '', f"Status: {result['status']}", '']
    for r in records:
        lines.append(f"- {r['mode']} / {r['phase']}: {r['seconds']} s; all-request hits {r['cache']['allRequestHitPercent']}%; non-cacheable {r['cache']['notCacheable']}")
    lines += ['', result.get('reason', result.get('limits', ''))]
    markdown = '\n'.join(lines) + '\n'
    (dist / 'pch-benchmark-summary.md').write_text(markdown, encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as out:
            out.write(markdown)
    print(markdown)
    if result['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    fresh = sub.add_parser('check-fresh')
    fresh.add_argument('--core-root', type=Path, required=True)
    fresh.add_argument('--report', type=Path, required=True)
    rec = sub.add_parser('record')
    rec.add_argument('--mode', choices=MODES, required=True)
    rec.add_argument('--phase', choices=PHASES, required=True)
    comp = sub.add_parser('compare')
    comp.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'check-fresh':
        check_fresh(args.core_root, args.report)
    elif args.command == 'record':
        record(args.mode, args.phase)
    else:
        compare(args.root)
