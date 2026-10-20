#!/usr/bin/env python3
import os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; BT=ROOT/'build_tools'
sys.path.insert(0,str(BT/'scripts')); sys.path.insert(0,str(BT/'scripts/core_common')); sys.path.insert(0,str(BT/'scripts/core_common/modules'))
os.chdir(BT)
import config, base, boost, icu, heif
config.parse(); config.parse_defaults()
base.set_env('BUILD_PLATFORM',config.option('platform'))

# The GitHub windows-2022 image has VS2022 with the v142 toolset, but no
# Visual Studio 2019 instance. Core's pinned HEIF builder derives the CMake
# generator from --vs-version=2019 and therefore asks CMake for VS16, which
# fails before x265 can be configured. Keep the Core compiler ABI at v142
# while selecting the installed VS2022 generator for these dependency builds.
if config.option('platform').startswith('win_'):
    heif.get_vs_version = lambda: '17 2022'
    _build_with_cmake = heif.build_with_cmake

    def _build_with_ci_cmake(platform, cmake_args, build_type):
        if platform.startswith('win_'):
            cmake_args = [*cmake_args, '-T', 'v142']
        return _build_with_cmake(platform, cmake_args, build_type)

    heif.build_with_cmake = _build_with_ci_cmake

print('=== Boost ==='); boost.make()
print('=== ICU ==='); icu.make()
print('=== HEIF ==='); heif.make()
heif_api = ROOT/'core/Common/3dParty/heif/libheif/libheif/api/libheif/heif.h'
if not heif_api.is_file():
    raise SystemExit(f'HEIF build did not materialize the required public header: {heif_api}')
print('Minimal X2T third-party build complete')
