#!/usr/bin/env python3
"""Persist Windows compiler-cache bytes independently from verified Core binaries.

Only disk is writable. A compatible snapshot can supply old source entries because
sccache validates each compiler invocation; it never bypasses the Core build.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def compatibility(env=None):
    env = os.environ if env is None else env
    version = json.loads((ROOT / 'config/build-acceleration.json').read_text())['sccacheVersion']
    result = {'schemaVersion': SCHEMA, 'platform': 'win_64', 'compilerVersion': env.get('X2T_COMPILER_VERSION', ''),
              'depsId': env.get('X2T_DEPS_ID', ''), 'sccacheVersion': version,
              'pchMode': env.get('X2T_PCH_MODE', ''), 'backend': 'disk'}
    if not result['compilerVersion'] or not result['depsId'] or result['pchMode'] != 'disabled':
        raise ValueError('Compiler, dependencies and explicit disabled PCH mode are required')
    return result


def identities(env=None):
    env = os.environ if env is None else env
    prefix = 'x2t-sccache-win_64-disk-v1-' + digest(compatibility(env)) + '-'
    parts = [env.get(k, '') for k in ('X2T_CORE_ID', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_JOB')]
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', value) for value in parts):
        raise ValueError('Missing or unsafe compiler snapshot identity')
    return prefix, prefix + '-'.join(parts)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def snapshot_root():
    return Path(os.environ['X2T_COMPILER_SNAPSHOT'])


def inventory(root):
    entries = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink in compiler snapshot')
        if path.is_file():
            entries.append({'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return entries


def configure():
    prefix, key = identities()
    root = Path(os.environ['RUNNER_TEMP']) / 'x2t-compiler-snapshot'
    if root.exists():
        raise ValueError('Expected a fresh compiler snapshot destination')
    (root / 'cache').mkdir(parents=True)
    values = {'X2T_COMPILER_SNAPSHOT': str(root), 'SCCACHE_DIR': str(root / 'cache'),
              'X2T_COMPILER_CACHE_PREFIX': prefix, 'X2T_COMPILER_CACHE_KEY': key}
    with Path(os.environ['GITHUB_ENV']).open('a', encoding='utf-8') as stream:
        for name, value in values.items():
            stream.write(f'{name}={value}\n')
    print(json.dumps({'prefix': prefix, 'key': key, 'backend': 'disk'}))


def verify_snapshot(root, expected):
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('compatibility') != expected:
        raise ValueError('Incompatible compiler snapshot')
    entries = inventory(root / 'cache')
    if not entries or digest(entries) != manifest.get('inventorySha256') or entries != manifest.get('files'):
        raise ValueError('Compiler snapshot content differs from manifest')
    return manifest


def restored():
    root = snapshot_root()
    matched = os.environ.get('X2T_COMPILER_CACHE_MATCHED_KEY', '')
    prefix, _ = identities()
    if matched:
        if not matched.startswith(prefix):
            raise ValueError('Unexpected compiler cache restore prefix')
        manifest = verify_snapshot(root, compatibility())
        if manifest.get('cacheKey') != matched:
            raise ValueError('Compiler snapshot manifest key differs from restored key')
        receipt = {'status': 'restored', 'key': matched, 'producerSourceSha': manifest.get('producerSourceSha'),
                   'fileCount': len(manifest['files']), 'inventorySha256': manifest['inventorySha256']}
    else:
        if (root / 'manifest.json').exists() or inventory(root / 'cache'):
            raise ValueError('Unidentified compiler snapshot bytes on cache miss')
        receipt = {'status': 'cold', 'key': None, 'fileCount': 0}
    write_json(ROOT / 'dist/compiler-cache-restore-win_64.json', receipt)
    print(json.dumps(receipt))


def validate_stats(raw):
    stats = raw['stats']
    if raw.get('version') != compatibility()['sccacheVersion']:
        raise ValueError('Unexpected sccache version')
    for key in ('cache_read_errors', 'cache_write_errors', 'cache_timeouts', 'compile_fails',
                'requests_not_cacheable', 'requests_unsupported_compiler'):
        if stats.get(key, 0):
            raise ValueError('Compiler cache failure: ' + key)
    if sum(stats.get('cache_errors', {}).get('counts', {}).values()):
        raise ValueError('Compiler cache backend error')
    levels = stats.get('multi_level') or []
    if len(levels) != 1 or levels[0].get('name') != 'disk':
        raise ValueError('Expected exactly one disk backend')
    if levels[0].get('write_failures', 0):
        raise ValueError('Disk backend write failure')
    requests = stats['compile_requests']
    hits = sum(stats['cache_hits']['counts'].values())
    misses = sum(stats['cache_misses']['counts'].values())
    if requests <= 0 or hits + misses != requests:
        raise ValueError('Expected real cacheable compilation requests')
    return {'requests': requests, 'hits': hits, 'misses': misses}


def finish():
    cache = os.environ['X2T_SCCACHE']
    raw = None
    try:
        deadline = time.monotonic() + 120
        while True:
            raw = json.loads(subprocess.check_output([cache, '--show-stats', '--stats-format', 'json'], text=True))
            counts = validate_stats(raw)
            if raw['stats'].get('cache_writes', 0) >= counts['misses']:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Compiler cache writes did not finish')
            time.sleep(1)
        metrics = json.loads((ROOT / 'dist/build-metrics-win_64.json').read_text())
        if metrics.get('exitCode') != 0 or metrics.get('pchMode') != 'disabled':
            raise ValueError('Build did not complete with disabled PCH')
    finally:
        if raw is not None:
            write_json(ROOT / 'dist/sccache-stats-win_64.json', raw)
        subprocess.run([cache, '--stop-server'], check=True)
        deadline = time.monotonic() + 30
        while 'sccache.exe' in subprocess.check_output(['tasklist', '/FI', 'IMAGENAME eq sccache.exe', '/FO', 'CSV', '/NH'], text=True).lower():
            if time.monotonic() >= deadline:
                raise RuntimeError('Compiler cache daemon did not stop')
            time.sleep(0.25)
    write_json(ROOT / 'dist/compiler-cache-quality-win_64.json', {'status': 'passed', **counts, 'backend': 'disk', 'daemonStopped': True})
    print(json.dumps({'status': 'passed', **counts, 'backend': 'disk'}))


def create_manifest(root, provenance=None):
    entries = inventory(root / 'cache')
    if not entries:
        raise ValueError('Refuse empty compiler snapshot')
    _, key = identities()
    manifest = {'schemaVersion': SCHEMA, 'compatibility': compatibility(), 'cacheKey': key,
                'producerSourceSha': os.environ['GITHUB_SHA'], 'coreId': os.environ['X2T_CORE_ID'],
                'files': entries, 'inventorySha256': digest(entries),
                'fileCount': len(entries), 'totalBytes': sum(e['bytes'] for e in entries)}
    if provenance:
        manifest['importedFrom'] = provenance
        manifest['importTargetCoreId'] = manifest.pop('coreId')
        manifest['producerSourceSha'] = provenance['actualSourceSha']
    write_json(root / 'manifest.json', manifest)
    write_json(ROOT / 'dist/compiler-cache-snapshot-win_64.json', {k:v for k,v in manifest.items() if k != 'files'})
    print(json.dumps({k:v for k,v in manifest.items() if k != 'files'}))
    return manifest


def pack():
    receipt = json.loads((ROOT / 'dist/compiler-cache-quality-win_64.json').read_text())
    if receipt.get('status') != 'passed' or receipt.get('daemonStopped') is not True:
        raise ValueError('Compiler snapshot requires successful strict validation')
    create_manifest(snapshot_root())


def import_seed(cache_root, inventory_path):
    """One-time migration utility; no fixed run/source/cache is embedded here."""
    import shutil
    expected = json.loads(inventory_path.read_text(encoding='utf-8'))
    entries = inventory(cache_root)
    fields = compatibility()
    if (digest(entries) != expected.get('inventorySha256') or entries != expected.get('files')
            or expected.get('depsId') != fields['depsId']
            or expected.get('compilerVersion') != fields['compilerVersion']
            or expected.get('sccacheVersion') != fields['sccacheVersion']
            or expected.get('imageVersion') != os.environ.get('ImageVersion')):
        raise ValueError('Seed bytes or environment do not match verified inventory')
    destination = snapshot_root() / 'cache'
    if inventory(destination):
        raise ValueError('Seed destination is not empty')
    shutil.copytree(cache_root, destination, dirs_exist_ok=True)
    create_manifest(snapshot_root(), {k: expected[k] for k in ('actualSourceSha', 'cacheKey', 'inventorySha256')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('configure', 'restored', 'finish', 'pack'):
        sub.add_parser(name)
    seed = sub.add_parser('import-seed')
    seed.add_argument('--cache-root', type=Path, required=True)
    seed.add_argument('--inventory', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'import-seed':
        import_seed(args.cache_root, args.inventory)
    else:
        globals()[args.command]()
