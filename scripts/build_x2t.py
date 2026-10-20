#!/usr/bin/env python3
import os, sys
from pathlib import Path
from branding import load_branding
ROOT=Path(__file__).resolve().parents[1]; BT=ROOT/'build_tools'; CORE=ROOT/'core'
organization, version, version_parts = load_branding()
os.environ['PUBLISHER_NAME'] = organization
os.environ['PRODUCT_VERSION'] = '.'.join(map(str, version_parts[:3]))
os.environ['BUILD_NUMBER'] = str(version_parts[3])
sys.path.insert(0,str(BT/'scripts')); os.chdir(BT)
import config, base, qmake
config.parse(); config.parse_defaults()
base.set_env('BUILD_PLATFORM',config.option('platform'))
project=CORE/'X2tConverter/build/Qt/X2tSLN.pro'
qmake.make_all_platforms(str(project))
print('X2T build complete')
