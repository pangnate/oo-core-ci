#!/usr/bin/env python3
"""Import a clean local Core checkout and matching runtime build inputs."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import download

ROOT = Path(__file__).resolve().parents[1]


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args]).decode('utf-8')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--core', type=Path, required=True)
    ap.add_argument('--linux-amd64', type=Path, required=True)
    ap.add_argument('--linux-arm64', type=Path, required=True)
    ap.add_argument('--windows-amd64', type=Path, required=True)
    args = ap.parse_args()
    source = args.core.resolve()
    target = (ROOT / 'core').resolve()
    if source == target or git(source, 'status', '--porcelain').strip():
        raise SystemExit('Core source must be a separate, clean Git checkout')
    for folder in (args.linux_amd64, args.linux_arm64, args.windows_amd64):
        if not folder.is_dir():
            raise SystemExit(f'Missing runtime source: {folder}')
    ref = git(source, 'rev-parse', 'HEAD').strip()
    files = sorted(filter(None, git(source, 'ls-files', '-z').split('\0')))
    old = set(filter(None, git(ROOT, 'ls-files', '-z', 'core/').split('\0')))
    incoming = {'core/' + name for name in files}
    # Preserve local branding; all other Core files follow the source snapshot.
    copyright_file = target / 'Common/copyright.txt'
    branding = copyright_file.read_bytes()
    for name in old - incoming:
        path = (ROOT / name).resolve()
        if not path.is_relative_to(target):
            raise RuntimeError(f'Unsafe obsolete path: {path}')
        path.unlink(missing_ok=True)
    digest = hashlib.sha256()
    for name in files:
        src, dst = source / name, target / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        digest.update(name.encode('utf-8') + b'\0' + hashlib.sha256(src.read_bytes()).digest())
    copyright_file.write_bytes(branding)
    download.patch_core()
    baseline = json.loads((ROOT / 'ci/baseline.json').read_text(encoding='utf-8'))
    baseline.update(coreRef=ref, coreSource=str(source), coreDescribe=git(source, 'describe', '--tags', '--always').strip())
    baseline['note'] = 'Local Core snapshot with preserved company branding and X2T CI patches. New baseline requires three-platform CI and conversion validation.'
    write_json(ROOT / 'ci/baseline.json', baseline)
    lock = json.loads(download.LOCK_FILE.read_text(encoding='utf-8'))
    lock['core-source'] = {'ref': ref, 'source': str(source), 'files': len(files),
                           'treeSha256': digest.hexdigest(),
                           'treeHashAlgorithm': 'sha256(sorted UTF-8 path + NUL + raw file SHA256)',
                           'overlays': ['Common/copyright.txt', 'X2tConverter/build/Qt/X2tSLN.pri', 'X2tConverter/build/Qt/X2tConverter.pro']}
    for key, folder, filename, pack in [
        ('runtime-linux-amd64', args.linux_amd64, 'linux-amd64-runtime.tar.gz', download.pack_linux_runtime),
        ('runtime-linux-arm64', args.linux_arm64, 'linux-arm64-runtime.tar.gz', download.pack_linux_runtime),
        ('runtime-windows-amd64', args.windows_amd64, 'windows-amd64-runtime.zip', download.pack_windows_runtime),
    ]:
        archive = download.RUNTIME / filename
        lock[key] = {'sha256': pack(folder.resolve(), archive), 'source': str(folder.resolve()),
                     'file': archive.relative_to(ROOT).as_posix()}
    write_json(download.LOCK_FILE, lock)
    deps = download.detect_dependency_inputs(json.loads((ROOT / 'config/deps.json').read_text(encoding='utf-8')))
    write_json(ROOT / 'vendor/detected-deps.json', deps)
    print(f'Synced {len(files)} Core files at {ref}; build_tools retained at {baseline["buildToolsRef"]}')


if __name__ == '__main__':
    main()
