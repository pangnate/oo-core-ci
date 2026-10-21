"""Static regression cases for behavior carried by the active Core patches.

These checks guard the patch contracts before a Core binary is available. They
do not replace conversion tests against a built X2T; those can use the named
scenarios here together with tests/core-features/fixtures.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERIES_PATH = ROOT / "patches" / "core" / "series.json"

# Each assertion is a behavior-bearing addition in the corresponding patch.
# Keeping cases mapped to patch files makes dropped or weakened patches visible
# in the normal unittest discovery run.
PATCH_CASES: dict[str, tuple[str, ...]] = {
    "025-share-presentation-namespaces-and-xlsb-types.patch": (
        "extern Namespaces g_Namespaces;",
        "Namespaces g_Namespaces;",
        "extern const FileType WorkbookBin;",
        '#include "../Binary/XlsbFormat/FileTypes_SpreadsheetBin.h"',
    ),
    "026-word-east-asian-layout-stream.patch": (
        "m_oStream.WriteLONG(EastAsianLayout.m_oID->GetValue());",
        'sResult += L"w:id=\\\"";',
        "sResult += m_oVertCompress->ToString();",
    ),
    "023-reduce-header-static-initialization.patch": (
        "inline const std::map<int, std::string>& GetEncodingsICU()",
        "static const wchar_t g_bstr_nodeclose[]",
        'static const CPath c_oContentTypeFileName (L"[Content_Types].xml");',
    ),
    "024-share-shape-and-color-tables.patch": (
        "extern const _shape_converter _OO_OOX_custom_shapes[205];",
        "extern const _shape_converter _OO_OOX_wordart[53];",
        "static const std::wstring standart_color[56]",
    ),
    "022-fix-texture-tile-path-clipping.patch": (
        "const bool isStretch = textureMode == c_BrushTextureModeStretch;",
        "if (isStretch && bIsEnableBrushRect)",
        "path = drawPath;",
    ),
    "020-word-preserve-protection-algorithm.patch": (
        'ComplexTypes_WriteAttribute(L"w:algorithmName=\\\"", m_oAlgorithmName);',
        "algorithmName is independent of the legacy crypt* attribute spelling.",
    ),
    "021-slide-preserve-spacing-namespace.patch": (
        'node.ReadNodeNoNS(L"spcPct")',
        'node.ReadNodeNoNS(L"spcPts")',
        "XmlUtils::GetNameNoNS(oReader.GetName())",
        "spcPct.reset();",
        "spcPts.reset();",
    ),
    "019-xls-share-default-palette.patch": (
        "extern const std::wstring DefaultPalette[64];",
        "const std::wstring DefaultPalette[64] = {",
    ),
    "003-word-distributed-jc.patch": (
        "align_Distribute = 4",
        "case SimpleTypes::jcDistribute",
        "case align_Distribute",
    ),
    "004-word-character-indents.patch": (
        "Ind_LeftChars = 206",
        "Ind_RightChars = 207",
        "Ind_FirstLineChars = 208",
        "Ind_HangingChars = 209",
        "Ind.m_oStartChars->GetValue()",
        "pInd->m_oHangingChars->SetValue",
    ),
    "005-word-east-asian-booleans.patch": (
        "pPr.m_oKinsoku.IsInit()",
        "pPr.m_oWordWrap.IsInit()",
        "pPr.m_oOverflowPunct.IsInit()",
        "pPr.m_oTopLinePunct.IsInit()",
        "pPr.m_oAutoSpaceDE.IsInit()",
        "pPr.m_oAutoSpaceDN.IsInit()",
        "FromBool(value != 0)",
    ),
    "007-word-permission-xml-spelling.patch": (
        'L"w:displacedByCustomXml"',
        'L"w:displacedbyCustomXml"',
        "!bHasStandardDisplacedByCustomXml && bHasLegacyDisplacedByCustomXml",
    ),
    "013-graphics-strict-image-errors.patch": (
        "struct ConversionPolicyV1",
        "ConversionImageFailedV1 = 1",
        "DrawImageFromFile(sImagePath, m1, m2, m3, m4)",
        "if (strictImages && status != S_OK)",
        "inline void Require(int count) const",
    ),
    "014-pdffile-strict-error-propagation.patch": (
        "OnlineWordToPdfV1(",
        "CommandsToPdfFromBinaryV1(",
        "CreatePdfCandidateV1(",
        'U_TO_UTF8((directory + L"/core-pdf-XXXXXX"))',
        "std::rename(sourceUtf8.c_str(), destinationUtf8.c_str())",
        "ConversionOutputFailedV1",
    ),
    "015-x2t-strict-image-policy.patch": (
        "m_sImageFailurePolicyV1",
        '== L"strict" || *m_sImageFailurePolicyV1 == L"1"',
        "ConvertPdfCommandsWithPolicyV1(",
        "const bool rawPdfCommands = conversion == TCD_BIN2PDF",
        "AVS_FILEUTILS_ERROR_CONVERT_PARAMS",
        "AVS_FILEUTILS_ERROR_CONVERT",
    ),
    "016-word-protection-source-omissions.patch": (
        'L"w:algorithmName"',
        'L"w:cryptAlgorithmSid"',
        'L"w:hashValue"',
        "formProt = 200",
        "pSectPr->m_oFormProt->m_oVal.FromBool(value != 0)",
    ),
    "017-slide-paragraph-stream-bools.patch": (
        '_T("eaLnBrk")',
        '_T("latinLnBrk")',
        '_T("hangingPunct")',
    ),
    "018-vml-ideographic-text-direction.patch": (
        "csslayoutflowVerticalIdeographic",
        'L"eaVert" : L"vert"',
    ),
}


def added_patch_text(path: Path) -> str:
    """Return only added diff lines, excluding diff metadata."""
    return "\n".join(
        line[1:]
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


class ActiveCorePatchCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.series = json.loads(SERIES_PATH.read_text(encoding="utf-8"))
        cls.active_paths = [Path(item["path"]).name for item in cls.series["patches"]]

    def test_every_active_patch_has_regression_cases(self) -> None:
        self.assertEqual(
            set(self.active_paths),
            set(PATCH_CASES),
            "Update PATCH_CASES when the active Core patch series changes.",
        )

    def test_patch_contract_cases(self) -> None:
        for patch_name, expected_additions in PATCH_CASES.items():
            with self.subTest(patch=patch_name):
                patch_path = ROOT / "patches" / "core" / patch_name
                self.assertTrue(patch_path.is_file(), f"missing active patch: {patch_path}")
                added = added_patch_text(patch_path)
                for expected in expected_additions:
                    with self.subTest(case=expected):
                        self.assertIn(expected, added)


if __name__ == "__main__":
    unittest.main()
