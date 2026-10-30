#!/usr/bin/env python3
"""Persist Linux compiler-cache bytes independently from verified Core binaries.

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


def target():
    value = os.environ.get('X2T_TARGET', '')
    if value not in ('linux_64', 'linux_arm64'):
        raise ValueError('Expected a Linux target')
    return value


def diagnostic(name):
    return ROOT / f'dist/{name}-{target()}.json'


def compatibility(env=None):
    env = os.environ if env is None else env
    platform = env.get('X2T_TARGET', '')
    if platform not in ('linux_64', 'linux_arm64'):
        raise ValueError('Expected a Linux target')
    version = json.loads((ROOT / 'config/build-acceleration.json').read_text())['sccacheVersion']
    inputs = json.loads((ROOT / f'dist/core-inputs-{platform}.json').read_text())['inputs']
    objects = inputs['gitObjects']
    result = {'schemaVersion': SCHEMA, 'platform': platform,
              'compilerVersion': inputs['compilerVersion'],
              'toolchainObjects': {p: objects[p] for p in
                                   ('ci/toolchains', 'vendor/checksums.json', 'vendor/detected-deps.json')},
              'depsId': env.get('X2T_DEPS_ID', ''), 'sccacheVersion': version,
              'pchMode': env.get('X2T_PCH_MODE', 'default'), 'backend': 'disk'}
    if (result['compilerVersion'] != 'locked-linux-sysroot' or not result['depsId']
            or result['pchMode'] != 'default' or inputs['platform'] != platform
            or inputs['depsId'] != result['depsId']):
        raise ValueError('Locked Linux toolchain, matching dependencies and default PCH required')
    return result


def identities(env=None):
    env = os.environ if env is None else env
    prefix = 'x2t-sccache-' + env['X2T_TARGET'] + '-disk-v1-' + digest(compatibility(env)) + '-'
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
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Snapshot cache must be a real directory')
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
    if root.is_symlink() or {p.name for p in root.iterdir()} != {'cache', 'manifest.json'}:
        raise ValueError('Unexpected compiler snapshot root entries')
    if (root / 'manifest.json').is_symlink():
        raise ValueError('Snapshot manifest must not be a symlink')
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schemaVersion') != SCHEMA or manifest.get('compatibility') != expected:
        raise ValueError('Incompatible compiler snapshot')
    entries = inventory(root / 'cache')
    if (not entries or digest(entries) != manifest.get('inventorySha256') or entries != manifest.get('files')
            or manifest.get('fileCount') != len(entries)
            or manifest.get('totalBytes') != sum(e['bytes'] for e in entries)):
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
                   'coreId': manifest.get('coreId'), 'fileCount': len(manifest['files']), 'inventorySha256': manifest['inventorySha256']}
    else:
        if root.is_symlink() or {p.name for p in root.iterdir()} != {'cache'} or inventory(root / 'cache'):
            raise ValueError('Unidentified compiler snapshot bytes on cache miss')
        receipt = {'status': 'cold', 'key': None, 'fileCount': 0}
    write_json(diagnostic('compiler-cache-restore'), receipt)
    print(json.dumps(receipt))


def validate_stats(raw, *, preflight=False):
    stats = raw['stats']
    if raw.get('version') != json.loads((ROOT / 'config/build-acceleration.json').read_text())['sccacheVersion']:
        raise ValueError('Unexpected sccache version')
    for key in ('cache_read_errors', 'cache_write_errors', 'cache_timeouts', 'compile_fails',
                'requests_not_cacheable', 'requests_unsupported_compiler', 'non_cacheable_compilations'):
        if stats.get(key, 0):
            raise ValueError('Compiler cache failure: ' + key)
    if sum(stats.get('cache_errors', {}).get('counts', {}).values()):
        raise ValueError('Compiler cache backend error')
    levels = stats.get('multi_level') or []
    if (not isinstance(levels, list) or len(levels) != 1
            or levels[0].get('name') != 'L0 (disk)'
            or raw.get('cache_location') != 'Multi-level (1 levels)'
            or not levels[0].get('location', '').startswith('Local disk: "')
            or not levels[0]['location'].endswith('"')):
        raise ValueError('Expected exactly one disk backend')
    location = levels[0]['location'][len('Local disk: \"'):-1]
    normalize = lambda value: os.path.normpath(value)
    if not os.environ.get('SCCACHE_DIR') or normalize(location) != normalize(os.environ['SCCACHE_DIR']):
        raise ValueError('Disk backend location differs from configured snapshot')
    if levels[0].get('write_failures', 0):
        raise ValueError('Disk backend write failure')
    requests = stats['compile_requests']
    hits = sum(stats['cache_hits']['counts'].values())
    misses = sum(stats['cache_misses']['counts'].values())
    if requests < 0 or (requests == 0 and not preflight) or hits + misses != requests:
        raise ValueError('Expected real cacheable compilation requests')
    return {'requests': requests, 'hits': hits, 'misses': misses}


def preflight():
    """Validate the actual daemon backend before spending time compiling."""
    raw = json.loads(subprocess.check_output(
        [os.environ['X2T_SCCACHE'], '--show-stats', '--stats-format', 'json'], text=True))
    write_json(diagnostic('sccache-preflight'), raw)
    counts = validate_stats(raw, preflight=True)
    if any(counts.values()) or raw['stats'].get('cache_writes', 0):
        raise ValueError('Expected reset compiler cache counters before compilation')
    print(json.dumps({'status': 'passed', 'phase': 'preflight', 'backend': 'disk', **counts}))


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
        metrics = json.loads((diagnostic('build-metrics')).read_text())
        if metrics.get('exitCode') != 0 or metrics.get('pchMode') != 'default':
            raise ValueError('Build did not complete with default PCH')
    finally:
        if raw is not None:
            write_json(diagnostic('sccache-stats'), raw)
        stop_server()
    write_json(diagnostic('compiler-cache-quality'), {'status': 'passed', **counts, 'backend': 'disk', 'daemonStopped': True})
    print(json.dumps({'status': 'passed', **counts, 'backend': 'disk'}))


def daemon_pids():
    """Dedicated host job: identify this pinned executable, ignoring dead zombies."""
    executable = Path(os.environ['X2T_SCCACHE']).resolve()
    result = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            if (directory / 'exe').resolve() == executable:
                status = (directory / 'status').read_text()
                if not re.search(r'^State:\s+Z', status, re.MULTILINE):
                    result.append(int(directory.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return result


def stop_server():
    # A fresh installation has no daemon. Never require --stop-server to succeed
    # before --zero-stats starts it, or on a previously stopped error path.
    if daemon_pids():
        subprocess.run([os.environ['X2T_SCCACHE'], '--stop-server'], check=True)
    deadline = time.monotonic() + 30
    while daemon_pids():
        if time.monotonic() >= deadline:
            raise RuntimeError('Compiler cache daemon did not stop')
        time.sleep(0.25)


def create_manifest(root):
    entries = inventory(root / 'cache')
    if not entries:
        raise ValueError('Refuse empty compiler snapshot')
    _, key = identities()
    manifest = {'schemaVersion': SCHEMA, 'compatibility': compatibility(), 'cacheKey': key,
                'producerSourceSha': os.environ['GITHUB_SHA'], 'coreId': os.environ['X2T_CORE_ID'],
                'files': entries, 'inventorySha256': digest(entries),
                'fileCount': len(entries), 'totalBytes': sum(e['bytes'] for e in entries)}
    write_json(root / 'manifest.json', manifest)
    write_json(diagnostic('compiler-cache-snapshot'), {k:v for k,v in manifest.items() if k != 'files'})
    print(json.dumps({k:v for k,v in manifest.items() if k != 'files'}))
    return manifest


def pack():
    receipt = json.loads((diagnostic('compiler-cache-quality')).read_text())
    if receipt.get('status') != 'passed' or receipt.get('daemonStopped') is not True:
        raise ValueError('Compiler snapshot requires successful strict validation')
    create_manifest(snapshot_root())



def saved():
    """actions/cache/save warns on upload failure; require an exact lookup."""
    _, key = identities()
    if os.environ.get('X2T_COMPILER_SAVED_KEY') != key:
        raise ValueError('Compiler snapshot was not confirmed under its exact save key')
    write_json(diagnostic('compiler-cache-saved'), {'status': 'passed', 'key': key})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('configure', 'restored', 'preflight', 'finish', 'pack', 'saved', 'stop_server'))
    globals()[parser.parse_args().command]()
