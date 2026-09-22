#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pri = ROOT / 'core' / 'X2tConverter' / 'build' / 'Qt' / 'X2tSLN.pri'
pro = ROOT / 'core' / 'X2tConverter' / 'build' / 'Qt' / 'X2tConverter.pro'

if not pri.exists():
    raise SystemExit(f'Missing {pri}; run scripts/download.py first')
text = pri.read_text(encoding='utf-8')
if 'CryptoPPLib \\\n' not in text.split('XlsbFormatLib')[0]:
    text = text.replace('SUBDIRS = \\\n', 'SUBDIRS = \\\n    CryptoPPLib \\\n', 1)
if 'CryptoPPLib.file' not in text:
    marker = 'XlsbFormatLib.file ='
    idx = text.find(marker)
    if idx < 0:
        raise SystemExit('Unexpected X2tSLN.pri layout: XlsbFormatLib.file not found')
    line = 'CryptoPPLib.file =\t../../../Common/3dParty/cryptopp/project/cryptopp.pro\n'
    text = text[:idx] + line + text[idx:]
if 'X2tConverter.depends = \\\n    CryptoPPLib \\\n' not in text:
    text = text.replace('X2tConverter.depends = \\\n', 'X2tConverter.depends = \\\n    CryptoPPLib \\\n', 1)
pri.write_text(text, encoding='utf-8', newline='\n')

# Make indirect DSO lookup deterministic on Linux when linking against a prebuilt runtime.
if pro.exists():
    ptext = pro.read_text(encoding='utf-8')
    block = "\n# BASEMETAS_X2T_CI_BEGIN\ncore_linux {\n    QMAKE_LFLAGS += -Wl,-rpath-link,$$CORE_BUILDS_LIBRARIES_PATH\n    QMAKE_LFLAGS += -Wl,-rpath-link,$$CORE_BUILDS_LIBRARIES_PATH/system\n}\n# BASEMETAS_X2T_CI_END\n"
    if '# BASEMETAS_X2T_CI_BEGIN' not in ptext:
        ptext += block
        pro.write_text(ptext, encoding='utf-8', newline='\n')
print('Patched X2tSLN.pri: CryptoPPLib is part of the solution')
print('Patched X2tConverter.pro: Linux rpath-link points to core/build/lib/<platform>')
