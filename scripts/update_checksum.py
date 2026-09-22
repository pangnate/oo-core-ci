#!/usr/bin/env python3
import hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
lock=ROOT/'vendor/checksums.json'
path=Path(sys.argv[1]).resolve()
key=sys.argv[2] if len(sys.argv)>2 else path.name
h=hashlib.sha256()
with path.open('rb') as f:
    for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
data=json.loads(lock.read_text(encoding='utf-8')) if lock.exists() else {}
data[key]={'sha256':h.hexdigest(),'file':path.relative_to(ROOT).as_posix() if ROOT in path.parents else path.as_posix()}
lock.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
print(h.hexdigest(), path)
