#!/usr/bin/env python3
import os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; BT=ROOT/'build_tools'; CORE=ROOT/'core'
sys.path.insert(0,str(BT/'scripts')); os.chdir(BT)
import config, base, qmake
config.parse(); config.parse_defaults()
base.set_env('BUILD_PLATFORM',config.option('platform'))
os.environ.setdefault('PRODUCT_VERSION','1.0.0'); os.environ.setdefault('BUILD_NUMBER','0')
project=CORE/'X2tConverter/build/Qt/X2tSLN.pro'
qmake.make_all_platforms(str(project))
print('X2T build complete')
