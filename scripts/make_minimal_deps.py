#!/usr/bin/env python3
import os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; BT=ROOT/'build_tools'
sys.path.insert(0,str(BT/'scripts')); sys.path.insert(0,str(BT/'scripts/core_common')); sys.path.insert(0,str(BT/'scripts/core_common/modules'))
os.chdir(BT)
import config, base, boost, icu
config.parse(); config.parse_defaults()
base.set_env('BUILD_PLATFORM',config.option('platform'))
print('=== Boost ==='); boost.make()
print('=== ICU ==='); icu.make()
print('Minimal X2T third-party build complete')
