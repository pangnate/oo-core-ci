#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
from native_sources import verify_archives

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'vendor/checksums.json'
DETECTED_FILE = ROOT / 'vendor/detected-deps.json'
DEFAULT_DEPS_FILE = ROOT / 'config/deps.json'


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def portable_path(value: str) -> Path:
    """Accept lock files generated on either Windows or POSIX hosts."""
    return ROOT / Path(value.replace('\\\\', '/').replace('\\', '/'))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--platform', choices=['linux', 'windows', 'all'], default='all')
    args = ap.parse_args()

    if not LOCK.exists():
        raise SystemExit('vendor/checksums.json missing; run scripts/download.py')

    detected_file = DETECTED_FILE if DETECTED_FILE.exists() else DEFAULT_DEPS_FILE
    detected = json.loads(detected_file.read_text(encoding='utf-8'))
    data = json.loads(LOCK.read_text(encoding='utf-8'))
    bad: list[str] = []
    try:
        verify_archives(ROOT)
    except (ValueError, OSError) as exc:
        bad.append(str(exc))

    common_keys = {'boost', 'icu', 'brotli'}
    linux_keys = {
        'qt_linux_amd64', 'qt_linux_arm64',
        'sysroot_linux_amd64', 'sysroot_linux_arm64',
        'python3_linux',
        'runtime-linux-amd64', 'runtime-linux-arm64',
    }
    windows_keys = {'qt_windows_amd64', 'runtime-windows-amd64'}

    selected_keys = set(common_keys)
    if args.platform in ('linux', 'all'):
        selected_keys |= linux_keys
    if args.platform in ('windows', 'all'):
        selected_keys |= windows_keys

    # Verify hashes only for inputs relevant to the requested platform.
    # Old lock files created on Windows may contain backslashes; normalize them.
    for key in selected_keys:
        item = data.get(key)
        if not item:
            bad.append(f'{key}: missing checksum lock entry')
            continue
        file = item.get('file')
        if not file:
            bad.append(f'{key}: missing archive path in checksum lock')
            continue
        path = portable_path(file)
        if not path.exists():
            bad.append(f'{key}: missing {path}')
            continue
        got = sha(path)
        expected = item.get('sha256')
        if not expected or got.lower() != expected.lower():
            bad.append(f'{key}: checksum {got} != {expected}')

    boost_minor = detected['boost']['version'].split('.')[1]
    icu_major, icu_minor = detected['icu']['version'].split('.')
    brotli_commit = detected['brotli']['commit']

    required_archives = [
        f'boost_1_{boost_minor}_0.tar.bz2',
        f'icu4c-{icu_major}_{icu_minor}-src.tgz',
        f'brotli-{brotli_commit}.tar.gz',
    ]

    if args.platform in ('linux', 'all'):
        required_archives += [
            detected['qt_linux_amd64'].get('filename', 'qt_binary_5.9.9_gcc_64.7z'),
            detected['qt_linux_arm64'].get('filename', 'qt_binary_5.9.9_gcc_arm64.7z'),
            detected['sysroot_linux_amd64'].get('filename', 'ubuntu16-amd64-sysroot.tar.gz'),
            detected['sysroot_linux_arm64'].get('filename', 'ubuntu16-arm64-sysroot.tar.gz'),
            'python3.tar.gz',
        ]
    if args.platform in ('windows', 'all'):
        required_archives += ['qt_5.15.2_msvc2019_64.7z']

    for name in required_archives:
        path = ROOT / 'vendor' / 'archives' / name
        if not path.exists():
            bad.append(f'missing {path}')

    if args.platform in ('linux', 'all'):
        for name in ['linux-amd64-runtime.tar.gz', 'linux-arm64-runtime.tar.gz']:
            path = ROOT / 'vendor' / 'runtime' / name
            if not path.exists():
                bad.append(f'missing {path}')

    if args.platform in ('windows', 'all'):
        path = ROOT / 'vendor' / 'runtime' / 'windows-amd64-runtime.zip'
        if not path.exists():
            bad.append(f'missing {path}')

    if bad:
        raise SystemExit('\n'.join(bad))

    print(f'Vendor inputs OK ({args.platform})')


if __name__ == '__main__':
    main()
