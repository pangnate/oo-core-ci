#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, tarfile, tempfile, zipfile, importlib.util
from pathlib import Path
from native_sources import prepare as prepare_native_sources
ROOT=Path(__file__).resolve().parents[1]
A=ROOT/'vendor'/'archives'; R=ROOT/'vendor'/'runtime'; W=ROOT/'vendor'/'work'; CORE=ROOT/'core'; BT=ROOT/'build_tools'
DETECTED=json.loads((ROOT/'vendor/detected-deps.json').read_text(encoding='utf-8')) if (ROOT/'vendor/detected-deps.json').exists() else json.loads((ROOT/'config/deps.json').read_text(encoding='utf-8'))

def run(*args, cwd=None):
    print('+',' '.join(map(str,args)))
    subprocess.run(list(map(str,args)),cwd=cwd,check=True)

def reset_dir(p):
    if p.exists(): shutil.rmtree(p)
    p.mkdir(parents=True,exist_ok=True)

def extract_tar_to_named(archive:Path,dest:Path,desired_root_name:str|None=None):
    tmp=Path(tempfile.mkdtemp(prefix='x2t-extract-',dir=str(W)))
    try:
        with tarfile.open(archive,'r:*') as tf: tf.extractall(tmp)
        children=[p for p in tmp.iterdir()]
        if desired_root_name:
            cand=tmp/desired_root_name
            if cand.exists(): src=cand
            elif len(children)==1 and children[0].is_dir(): src=children[0]
            else: raise RuntimeError(f'Cannot identify root in {archive}: {children}')
        else:
            if len(children)!=1: raise RuntimeError(f'Unexpected archive root {archive}: {children}')
            src=children[0]
        if dest.exists(): shutil.rmtree(dest)
        shutil.move(str(src),str(dest))
    finally: shutil.rmtree(tmp,ignore_errors=True)

def prepare_sources():
    W.mkdir(parents=True,exist_ok=True)
    prepare_native_sources(CORE, ROOT)
    boostver=DETECTED['boost']['version']; boostminor=boostver.split('.')[1]
    boostname=f'boost_1_{boostminor}_0'
    boostdir=CORE/'Common/3dParty/boost'
    extract_tar_to_named(A/f'{boostname}.tar.bz2',boostdir/boostname)
    (boostdir/'boost.data').write_text('boost_version_'+str(DETECTED['boost'].get('moduleVersion','5')),encoding='utf-8')
    icuver=DETECTED['icu']['version']; imaj,imin=icuver.split('.')
    icudir=CORE/'Common/3dParty/icu'
    extract_tar_to_named(A/f'icu4c-{imaj}_{imin}-src.tgz',icudir/'icu','icu')
    (icudir/'module.version').write_text(str(DETECTED['icu'].get('moduleVersion','8')),encoding='utf-8')
    commit=DETECTED['brotli']['commit']
    brotlidir=CORE/'Common/3dParty/brotli'
    extract_tar_to_named(A/f'brotli-{commit}.tar.gz',brotlidir/'brotli')
    (brotlidir/'module.version').write_text(str(DETECTED['brotli'].get('moduleVersion','1')),encoding='utf-8')

def load_sysroot_fetch():
    sys.path.insert(0,str(BT/'scripts'))
    spec=importlib.util.spec_from_file_location('oo_sysroot_fetch',BT/'tools/linux/sysroot/fetch.py')
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def patch_linux_sysroot_check():
    # The upstream parser requires both architectures even for amd64 and
    # downloads them if either is absent. Preparation owns all locked inputs.
    path=BT/'scripts/config.py'
    text=path.read_text(encoding='utf-8')
    original=('      if not base.is_dir(dst_dir_amd64) or not base.is_dir(dst_dir_arm64):\n'
              '        base.cmd_in_dir(dst_dir, "python3", ["./fetch.py", "all"])')
    replacement=('      # X2T_LOCKED_SYSROOTS: arm64 also needs the amd64 host toolchain.\n'
                 '      if not base.is_dir(dst_dir_amd64) or (check_option("platform", "linux_arm64") and not base.is_dir(dst_dir_arm64)):\n'
                 '        raise RuntimeError("Missing locked sysroot; run scripts/prepare.py for the configured target")')
    if original in text:
        path.write_text(text.replace(original,replacement,1),encoding='utf-8')
    elif replacement not in text:
        raise RuntimeError('Unexpected build_tools sysroot check; refusing an unchecked adaptation')

def prepare_linux(target=None):
    prepare_sources()
    selected_target=target
    need_arm=target in (None,'linux_arm64')
    qver=DETECTED['qt_linux_amd64'].get('version','5.9.9')
    qtroot=BT/f'tools/linux/qt_build/Qt-{qver}'; reset_dir(qtroot)
    run('7z','x','-y',f'-o{qtroot}',A/DETECTED['qt_linux_amd64'].get('filename',f'qt_binary_{qver}_gcc_64.7z'))
    if need_arm:
        run('7z','x','-y',f'-o{qtroot}',A/DETECTED['qt_linux_arm64'].get('filename',f'qt_binary_{qver}_gcc_arm64.7z'))
    sys.path.insert(0,str(BT/'scripts'))
    import base
    base.setup_local_qmake(str(qtroot/'gcc_64/bin'))
    if need_arm:
        base.setup_local_qmake(str(qtroot/'gcc_arm64/bin'))
        arm=qtroot/'gcc_arm64'
        if (arm/'_bin').exists(): shutil.rmtree(arm/'_bin')
        shutil.move(str(arm/'bin'),str(arm/'_bin'))
        shutil.copytree(qtroot/'gcc_64/bin',arm/'bin',symlinks=True)
    # build_tools calls base.check_python() while switching sysroot env.
    # Preinstall ONLYOFFICE's portable Python so it never downloads during CI.
    pyroot=BT/'tools/linux/python3'
    if pyroot.exists(): shutil.rmtree(pyroot)
    with tarfile.open(A/'python3.tar.gz','r:gz') as tf: tf.extractall(BT/'tools/linux')
    if not (pyroot/'bin/python3').exists(): raise RuntimeError('Portable ONLYOFFICE python3 archive has unexpected layout')

    sroot=BT/'tools/linux/sysroot'; sroot.mkdir(parents=True,exist_ok=True)
    for arch,fn in [('amd64',DETECTED['sysroot_linux_amd64'].get('filename','ubuntu16-amd64-sysroot.tar.gz')),('arm64',DETECTED['sysroot_linux_arm64'].get('filename','ubuntu16-arm64-sysroot.tar.gz'))]:
        if arch=='arm64' and not need_arm: continue
        d=sroot/f'ubuntu16-{arch}-sysroot'
        if d.exists(): shutil.rmtree(d)
        with tarfile.open(A/fn,'r:gz') as tf: tf.extractall(sroot)
    # build_tools ignores this required amd64 HEIF toolchain file (*sysroot*).
    # Keep its source tracked by this repository and materialize it for clean CI checkouts.
    toolchain_template=ROOT/'ci/toolchains/linux-amd64-custom-sysroot.toolchain.cmake'
    toolchain_target=sroot/'custom-sysroot.toolchain.cmake'
    if not toolchain_template.is_file(): raise RuntimeError(f'Missing tracked sysroot toolchain template: {toolchain_template}')
    shutil.copyfile(toolchain_template,toolchain_target)
    fetch=load_sysroot_fetch(); fetch.patch_linker_scripts(str(sroot/'ubuntu16-amd64-sysroot'),'amd64')
    if need_arm: fetch.patch_linker_scripts(str(sroot/'ubuntu16-arm64-sysroot'),'arm64')
    patch_linux_sysroot_check()
    for target,fn in [('linux_64','linux-amd64-runtime.tar.gz'),('linux_arm64','linux-arm64-runtime.tar.gz')]:
        if selected_target is not None and target!=selected_target: continue
        out=CORE/'build/lib'/target; reset_dir(out)
        with tarfile.open(R/fn,'r:gz') as tf: tf.extractall(out)
    print('Linux inputs prepared')

def prepare_windows(runtime_only=False):
    if not runtime_only: prepare_sources()
    W.mkdir(parents=True,exist_ok=True)
    qtroot=W/'qt-win/Qt-5.15.2'; reset_dir(qtroot)
    run('7z','x','-y',f'-o{qtroot}',A/'qt_5.15.2_msvc2019_64.7z')
    q=qtroot/'msvc2019_64/bin/qmake.exe'
    if not q.exists(): raise RuntimeError(f'Missing {q}')
    out=CORE/'build/lib/win_64'; reset_dir(out)
    with zipfile.ZipFile(R/'windows-amd64-runtime.zip') as z: z.extractall(out)
    print('Windows inputs prepared')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--platform',choices=['linux','windows'],required=True); ap.add_argument('--target',choices=['linux_64','linux_arm64']); ap.add_argument('--runtime-only',action='store_true'); args=ap.parse_args()
    if not CORE.exists() or not BT.exists(): raise SystemExit('core/ and build_tools/ are missing; run scripts/download.py locally first and commit them')
    if args.platform=='linux':
        if args.runtime_only: ap.error('--runtime-only is only used by Windows runtime verification')
        prepare_linux(args.target)
    else:
        if args.target: ap.error('--target is only valid for Linux')
        prepare_windows(args.runtime_only)
if __name__=='__main__': main()
