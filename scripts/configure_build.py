#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; BT=ROOT/'build_tools'; W=ROOT/'vendor/work'
import json
DETECTED=json.loads((ROOT/'vendor/detected-deps.json').read_text(encoding='utf-8')) if (ROOT/'vendor/detected-deps.json').exists() else {'qt_linux_amd64':{'version':'5.9.9'}}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--platform',choices=['linux','windows'],required=True); ap.add_argument('--vs-path'); args=ap.parse_args()
    cmd=[sys.executable,str(BT/'configure.py'),'--update','0','--module','core','--config','no_tests','--clean','1']
    if args.platform=='linux':
        cmd += ['--platform','linux_64 linux_arm64','--sysroot','1','--qt-dir',str(BT/f"tools/linux/qt_build/Qt-{DETECTED['qt_linux_amd64'].get('version','5.9.9')}").replace('\\','/')]
    else:
        if not args.vs_path: raise SystemExit('--vs-path is required for windows')
        cmd += ['--platform','win_64','--vs-version','2019','--vs-path',args.vs_path.replace('\\','/'),'--qt-dir',str(W/'qt-win/Qt-5.15.2').replace('\\','/')]
    print('+',' '.join(cmd)); subprocess.run(cmd,check=True)
if __name__=='__main__': main()
