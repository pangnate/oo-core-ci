#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; LOCK=ROOT/'vendor/checksums.json'
DETECTED=json.loads((ROOT/'vendor/detected-deps.json').read_text(encoding='utf-8')) if (ROOT/'vendor/detected-deps.json').exists() else json.loads((ROOT/'config/deps.json').read_text(encoding='utf-8'))
def sha(p):
 h=hashlib.sha256(); f=p.open('rb')
 with f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--platform',choices=['linux','windows','all'],default='all'); a=ap.parse_args()
 if not LOCK.exists(): raise SystemExit('vendor/checksums.json missing; run scripts/download.py')
 data=json.loads(LOCK.read_text(encoding='utf-8')); bad=[]
 for k,v in data.items():
  file=v.get('file')
  if not file: continue
  p=ROOT/file
  if not p.exists(): bad.append(f'{k}: missing {p}'); continue
  got=sha(p)
  if got.lower()!=v['sha256'].lower(): bad.append(f'{k}: checksum {got} != {v["sha256"]}')
 if bad: raise SystemExit('\n'.join(bad))
 bminor=DETECTED['boost']['version'].split('.')[1]; imaj,imin=DETECTED['icu']['version'].split('.'); commit=DETECTED['brotli']['commit']
 req=[f'boost_1_{bminor}_0.tar.bz2',f'icu4c-{imaj}_{imin}-src.tgz',f'brotli-{commit}.tar.gz']
 if a.platform in ('linux','all'): req += [DETECTED['qt_linux_amd64'].get('filename','qt_binary_5.9.9_gcc_64.7z'),DETECTED['qt_linux_arm64'].get('filename','qt_binary_5.9.9_gcc_arm64.7z'),DETECTED['sysroot_linux_amd64'].get('filename','ubuntu16-amd64-sysroot.tar.gz'),DETECTED['sysroot_linux_arm64'].get('filename','ubuntu16-arm64-sysroot.tar.gz'),'python3.tar.gz']
 if a.platform in ('windows','all'): req += ['qt_5.15.2_msvc2019_64.7z']
 for n in req:
  if not (ROOT/'vendor/archives'/n).exists(): bad.append('missing vendor/archives/'+n)
 if a.platform in ('linux','all'):
  for n in ['linux-amd64-runtime.tar.gz','linux-arm64-runtime.tar.gz']:
   if not (ROOT/'vendor/runtime'/n).exists(): bad.append('missing vendor/runtime/'+n)
 if a.platform in ('windows','all') and not (ROOT/'vendor/runtime/windows-amd64-runtime.zip').exists(): bad.append('missing vendor/runtime/windows-amd64-runtime.zip')
 if bad: raise SystemExit('\n'.join(bad))
 print('Vendor inputs OK')
if __name__=='__main__': main()
