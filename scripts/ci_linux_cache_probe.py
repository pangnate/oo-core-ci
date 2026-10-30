#!/usr/bin/env python3
"""Live native-host disk-cache contract probe, not an X2T/ARM runtime test."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import ci_linux_compiler_cache as cache


def settled_stats():
    deadline=time.monotonic()+30
    while True:
        raw=json.loads(subprocess.check_output([os.environ['X2T_SCCACHE'],'--show-stats','--stats-format','json'],text=True))
        counts=cache.validate_stats(raw)
        if raw['stats'].get('cache_writes',0)>=counts['misses']:
            return raw,counts
        if time.monotonic()>=deadline:
            raise RuntimeError('Probe disk writes did not finish')
        time.sleep(.25)


def main():
    root=Path(os.environ['RUNNER_TEMP'])/'linux-cache-live-probe'
    root.mkdir()  # require a new isolated probe
    os.environ['SCCACHE_DIR']=str(root/'cache')
    os.environ['SCCACHE_MULTILEVEL_CHAIN']='disk'
    if any(k.startswith('SCCACHE_GHA') or k=='SCCACHE_IGNORE_SERVER_IO_ERROR' for k in os.environ):
        raise ValueError('Probe must not inherit GHA or ignored I/O settings')
    executable=os.environ.get('SCCACHE_PATH') or shutil.which('sccache')
    if not executable:raise RuntimeError('Pinned sccache action must run first')
    os.environ['X2T_SCCACHE']=str(Path(executable).resolve())
    os.environ['X2T_TARGET']='linux_64'
    source=root/'probe.cpp';obj=root/'probe.o'
    source.write_text('int square(int n) { return n*n; }\n')
    try:
        subprocess.run([executable,'--zero-stats'],check=True)
        cache.preflight()
        command=[executable,'g++','-c',str(source),'-o',str(obj)]
        subprocess.run(command,check=True)
        cold,cold_counts=settled_stats()
        if cold_counts!={'requests':1,'hits':0,'misses':1}:
            raise ValueError('Isolated live probe did not write its cold object')
        sha=hashlib.sha256(obj.read_bytes()).hexdigest();obj.unlink()
        subprocess.run(command,check=True)
        warm,warm_counts=settled_stats()
        if warm_counts!={'requests':2,'hits':1,'misses':1} or hashlib.sha256(obj.read_bytes()).hexdigest()!=sha:
            raise ValueError('Live probe did not reuse identical object bytes')
        cache.write_json(cache.ROOT/'dist/linux-cache-probe-cold.json',cold)
        cache.write_json(cache.ROOT/'dist/linux-cache-probe-warm.json',warm)
    finally:
        cache.stop_server()
    cache.write_json(cache.ROOT/'dist/linux-cache-probe.json',{'status':'passed','scope':'native-host-g++-only',
        'cold':cold_counts,'warm':warm_counts,'objectSha256':sha,'daemonStopped':True})


if __name__=='__main__':main()
