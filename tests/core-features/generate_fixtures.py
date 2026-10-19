#!/usr/bin/env python3
"""Build deterministic OOXML fixtures from the product's blank office templates."""
from __future__ import annotations

import hashlib
import itertools
import json
import argparse
import shutil
import struct
import zlib
import zipfile
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "tests" / "core-features" / "fixtures"
NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("w", NS_W)
ET.register_namespace("a", NS_A)
ET.register_namespace("p", NS_P)
ET.register_namespace("r", NS_R)
ET.register_namespace("", NS_X)


def tag(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}"


def png_chunk(name: bytes, data: bytes) -> bytes:
    body = name + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)


def make_png() -> bytes:
    # 8x8 RGB checkerboard, fully deterministic and independent of image packages.
    rows = []
    for y in range(8):
        row = bytearray([0])
        for x in range(8):
            row.extend((48, 112, 192) if (x + y) % 2 else (230, 240, 250))
        rows.append(bytes(row))
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
            + png_chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + png_chunk(b"IEND", b""))


def replace_zip_part(source: Path, dest: Path, replacements: dict[str, bytes]) -> None:
    with zipfile.ZipFile(source, "r") as inp, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for item in inp.infolist():
            out.writestr(item, replacements.pop(item.filename, inp.read(item.filename)))
        for name, data in replacements.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            out.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def make_word() -> None:
    root = ET.Element(tag(NS_W, "document"))
    body = ET.SubElement(root, tag(NS_W, "body"))
    # 4 Chars fields x six booleans. Explicit zero and false remain distinguishable from omission.
    char_names = ("leftChars", "rightChars", "firstLineChars", "hangingChars")
    bool_names = ("kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN")
    for char_values in itertools.product((0, 80), repeat=4):
        for bool_values in itertools.product((False, True), repeat=6):
            p = ET.SubElement(body, tag(NS_W, "p"))
            pp = ET.SubElement(p, tag(NS_W, "pPr"))
            ind = ET.SubElement(pp, tag(NS_W, "ind"))
            for name, value in zip(char_names, char_values):
                ind.set(tag(NS_W, name), str(value))
            for name, value in zip(bool_names, bool_values):
                node = ET.SubElement(pp, tag(NS_W, name))
                node.set(tag(NS_W, "val"), "1" if value else "0")
            text = ET.SubElement(ET.SubElement(p, tag(NS_W, "r")), tag(NS_W, "t"))
            text.text = f"chars={char_values};bools={tuple(int(v) for v in bool_values)}"
    # Existing line spacing and character scaling values, with explicit zero and omission examples.
    for lines in (0, 50, 100, 200):
        for scale in (None, 80, 100, 120):
            p = ET.SubElement(body, tag(NS_W, "p"))
            pp = ET.SubElement(p, tag(NS_W, "pPr"))
            ET.SubElement(pp, tag(NS_W, "spacing"), {tag(NS_W, "beforeLines"): str(lines), tag(NS_W, "afterLines"): str(lines)})
            rpr = ET.SubElement(ET.SubElement(p, tag(NS_W, "r")), tag(NS_W, "rPr"))
            if scale is not None:
                ET.SubElement(rpr, tag(NS_W, "w"), {tag(NS_W, "val"): str(scale)})
            ET.SubElement(ET.SubElement(p, tag(NS_W, "r")), tag(NS_W, "t")).text = f"lines={lines};scale={scale}"
    # Distributed alignment and all marker/permission attributes without passwords or user data.
    for jc in ("left", "right", "center", "both", "distribute"):
        p = ET.SubElement(body, tag(NS_W, "p"))
        pp = ET.SubElement(p, tag(NS_W, "pPr"))
        ET.SubElement(pp, tag(NS_W, "jc"), {tag(NS_W, "val"): jc})
        ET.SubElement(ET.SubElement(p, tag(NS_W, "r")), tag(NS_W, "t")).text = "alignment=" + jc
    p = ET.SubElement(body, tag(NS_W, "p"))
    ET.SubElement(p, tag(NS_W, "permStart"), {tag(NS_W, "id"): "17", tag(NS_W, "ed"): "editor@example.invalid"})
    ET.SubElement(p, tag(NS_W, "permEnd"), {tag(NS_W, "id"): "17"})
    ET.SubElement(p, tag(NS_W, "permStart"), {tag(NS_W, "id"): "18", tag(NS_W, "edGrp"): "everyone",
                                                tag(NS_W, "colFirst"): "1", tag(NS_W, "colLast"): "3",
                                                tag(NS_W, "displacedByCustomXml"): "next"})
    ET.SubElement(p, tag(NS_W, "permEnd"), {tag(NS_W, "id"): "18"})
    ET.SubElement(body, tag(NS_W, "sectPr"))
    template = DEST / "source-blank.docx"
    if not template.is_file():
        raise SystemExit(f"product source template missing: {template}")
    dest = DEST / "word-core-features.docx"
    replace_zip_part(template, dest, {"word/document.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True)})


def make_slide() -> None:
    template = DEST / "source-blank.pptx"
    if not template.is_file():
        raise SystemExit(f"product source template missing: {template}")
    with zipfile.ZipFile(template, "r") as z:
        root = ET.fromstring(z.read("ppt/slides/slide1.xml"))
    tree = root.find(f".//{tag(NS_P, 'spTree')}")
    assert tree is not None
    shapes = tree.findall(tag(NS_P, "sp"))
    text_body = shapes[0].find(tag(NS_P, "txBody"))
    assert text_body is not None
    for algn in ("l", "ctr", "r", "just", "dist", "justLow", "thaiDist"):
        for rtl, ea, latin in itertools.product((False, True), repeat=3):
            para = ET.SubElement(text_body, tag(NS_A, "p"))
            attrs = {"algn": algn, "rtl": "1" if rtl else "0", "eaLnBrk": "1" if ea else "0", "latinLnBrk": "1" if latin else "0"}
            ET.SubElement(para, tag(NS_A, "pPr"), attrs)
            ET.SubElement(ET.SubElement(para, tag(NS_A, "r")), tag(NS_A, "t")).text = "alignment fixture"
    for kind, attr, value in (("pct", "val", "75000"), ("pts", "val", "1800")):
        para = ET.SubElement(text_body, tag(NS_A, "p"))
        props = ET.SubElement(para, tag(NS_A, "pPr"))
        ln = ET.SubElement(props, tag(NS_A, "lnSpc"))
        ET.SubElement(ln, tag(NS_A, kind), {attr: value})
        ET.SubElement(ET.SubElement(para, tag(NS_A, "r")), tag(NS_A, "t")).text = f"line-spacing-{kind}"
    for direction in ("horz", "vert", "vert270", "eaVert"):
        sp = deepcopy(shapes[1])
        nv = sp.find(f".//{tag(NS_P, 'cNvPr')}")
        assert nv is not None
        nv.set("id", str(10 + len(tree.findall(tag(NS_P, "sp")))))
        nv.set("name", f"Direction {direction}")
        body_pr = sp.find(f".//{tag(NS_A, 'bodyPr')}")
        assert body_pr is not None
        body_pr.set("vert", direction)
        tree.append(sp)
    dest = DEST / "slide-core-features.pptx"
    replace_zip_part(template, dest, {"ppt/slides/slide1.xml": ET.tostring(root, encoding="utf-8", xml_declaration=True)})


def make_sheet() -> None:
    template = DEST / "source-blank.xlsx"
    if not template.is_file():
        raise SystemExit(f"product source template missing: {template}")
    with zipfile.ZipFile(template, "r") as z:
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    sheets = workbook.find(tag(NS_X, "sheets"))
    assert sheets is not None
    sheets.clear()
    replacements: dict[str, bytes] = {}
    relationship_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    # Replace the single blank-template worksheet relationship with a deterministic set.
    rels.clear()
    for idx, title in enumerate(("SharedBackground", "FilledCells", "NoGridMultiPage", "RepeatedTitles"), start=1):
        ET.SubElement(sheets, tag(NS_X, "sheet"), {"name": title, "sheetId": str(idx), tag(NS_R, "id"): f"rId{idx}"})
        ET.SubElement(rels, tag(relationship_ns, "Relationship"), {"Id": f"rId{idx}", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet", "Target": f"worksheets/sheet{idx}.xml"})
        ws = ET.Element(tag(NS_X, "worksheet"))
        ET.SubElement(ws, tag(NS_X, "dimension"), {"ref": "A1:AD150"})
        views = ET.SubElement(ws, tag(NS_X, "sheetViews"))
        ET.SubElement(views, tag(NS_X, "sheetView"), {"workbookViewId": "0", "showGridLines": "0" if idx == 3 else "1"})
        ET.SubElement(ws, tag(NS_X, "sheetFormatPr"), {"defaultRowHeight": "15"})
        data = ET.SubElement(ws, tag(NS_X, "sheetData"))
        for row_num in range(1, 151):
            row = ET.SubElement(data, tag(NS_X, "row"), {"r": str(row_num)})
            for col in range(1, 31):
                ref = f"{chr(64 + col)}{row_num}"
                cell_attrs = {"r": ref, "t": "inlineStr"}
                if idx == 2 and row_num == 1 and col == 1:
                    cell_attrs["s"] = "1"
                cell = ET.SubElement(row, tag(NS_X, "c"), cell_attrs)
                inline = ET.SubElement(cell, tag(NS_X, "is"))
                ET.SubElement(inline, tag(NS_X, "t")).text = f"{title} {ref}"
        ET.SubElement(ws, tag(NS_X, "printOptions"), {"gridLines": "0"})
        ET.SubElement(ws, tag(NS_X, "pageMargins"), {"left": "0.25", "right": "0.25", "top": "0.5", "bottom": "0.5", "header": "0.2", "footer": "0.2"})
        ET.SubElement(ws, tag(NS_X, "pageSetup"), {"fitToWidth": "1", "fitToHeight": "0", "orientation": "landscape"})
        if idx in (1, 2):
            ET.SubElement(ws, tag(NS_X, "picture"), {tag(NS_R, "id"): "rId1"})
            relroot = ET.Element(tag(relationship_ns, "Relationships"))
            ET.SubElement(relroot, tag(relationship_ns, "Relationship"), {"Id": "rId1", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", "Target": "../media/known.png"})
            replacements[f"xl/worksheets/_rels/sheet{idx}.xml.rels"] = ET.tostring(relroot, encoding="utf-8", xml_declaration=True)
        replacements[f"xl/worksheets/sheet{idx}.xml"] = ET.tostring(ws, encoding="utf-8", xml_declaration=True)
    defined = ET.SubElement(workbook, tag(NS_X, "definedNames"))
    ET.SubElement(defined, tag(NS_X, "definedName"), {"name": "_xlnm.Print_Titles", "localSheetId": "3"}).text = "'RepeatedTitles'!$1:$3"
    ET.SubElement(rels, tag(relationship_ns, "Relationship"), {"Id": "rId5", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "Target": "styles.xml"})
    replacements["xl/workbook.xml"] = ET.tostring(workbook, encoding="utf-8", xml_declaration=True)
    replacements["xl/_rels/workbook.xml.rels"] = ET.tostring(rels, encoding="utf-8", xml_declaration=True)
    styles = ET.Element(tag(NS_X, "styleSheet"))
    fonts = ET.SubElement(styles, tag(NS_X, "fonts"), {"count": "1"})
    ET.SubElement(fonts, tag(NS_X, "font"))
    fills = ET.SubElement(styles, tag(NS_X, "fills"), {"count": "2"})
    ET.SubElement(fills, tag(NS_X, "fill")).append(ET.Element(tag(NS_X, "patternFill"), {"patternType": "none"}))
    fill = ET.SubElement(fills, tag(NS_X, "fill"))
    pattern = ET.SubElement(fill, tag(NS_X, "patternFill"), {"patternType": "solid"})
    ET.SubElement(pattern, tag(NS_X, "fgColor"), {"rgb": "FFB7DEE8"})
    ET.SubElement(pattern, tag(NS_X, "bgColor"), {"indexed": "64"})
    borders = ET.SubElement(styles, tag(NS_X, "borders"), {"count": "1"})
    ET.SubElement(borders, tag(NS_X, "border"))
    xfs = ET.SubElement(styles, tag(NS_X, "cellStyleXfs"), {"count": "1"})
    ET.SubElement(xfs, tag(NS_X, "xf"), {"numFmtId": "0", "fontId": "0", "fillId": "0", "borderId": "0"})
    cell_xfs = ET.SubElement(styles, tag(NS_X, "cellXfs"), {"count": "2"})
    ET.SubElement(cell_xfs, tag(NS_X, "xf"), {"numFmtId": "0", "fontId": "0", "fillId": "0", "borderId": "0", "xfId": "0"})
    ET.SubElement(cell_xfs, tag(NS_X, "xf"), {"numFmtId": "0", "fontId": "0", "fillId": "1", "borderId": "0", "xfId": "0", "applyFill": "1"})
    cell_styles = ET.SubElement(styles, tag(NS_X, "cellStyles"), {"count": "1"})
    ET.SubElement(cell_styles, tag(NS_X, "cellStyle"), {"name": "Normal", "xfId": "0", "builtinId": "0"})
    replacements["xl/styles.xml"] = ET.tostring(styles, encoding="utf-8", xml_declaration=True)
    content_types = ET.fromstring(zipfile.ZipFile(template, "r").read("[Content_Types].xml"))
    ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    for idx in range(2, 5):
        ET.SubElement(content_types, tag(ct_ns, "Override"), {"PartName": f"/xl/worksheets/sheet{idx}.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"})
    ET.SubElement(content_types, tag(ct_ns, "Override"), {"PartName": "/xl/styles.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"})
    ET.SubElement(content_types, tag(ct_ns, "Default"), {"Extension": "png", "ContentType": "image/png"})
    replacements["[Content_Types].xml"] = ET.tostring(content_types, encoding="utf-8", xml_declaration=True)
    replacements["xl/media/known.png"] = (DEST / "known.png").read_bytes()
    dest = DEST / "sheet-core-features.xlsx"
    replace_zip_part(template, dest, replacements)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, help="optional directory containing blank.docx, blank.pptx, and blank.xlsx")
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    if args.source_root:
        for name in ("blank.docx", "blank.pptx", "blank.xlsx"):
            source = args.source_root / name
            if not source.is_file():
                raise SystemExit(f"product source template missing: {source}")
            shutil.copyfile(source, DEST / f"source-{name}")
    for name in ("blank.docx", "blank.pptx", "blank.xlsx"):
        if not (DEST / f"source-{name}").is_file():
            raise SystemExit(f"copied source template missing: {DEST / f'source-{name}'}")
    (DEST / "known.png").write_bytes(make_png())
    # Deliberately invalid PNG: a valid signature and IHDR marker with corrupt CRC/truncated stream.
    (DEST / "bad.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x08\x00\x00\x00\x08\x08\x02\x00\x00\x00broken")
    make_word()
    make_slide()
    make_sheet()
    files = sorted(p for p in DEST.iterdir() if p.is_file() and p.name != "manifest.json")
    manifest = {"schemaVersion": 1, "sourceRoot": "D:/docservice/idp-all/idp-example/public/templates",
                "sourceTemplates": {name: hashlib.sha256((DEST / f"source-{name}").read_bytes()).hexdigest()
                                    for name in ("blank.docx", "blank.pptx", "blank.xlsx")},
                "expectations": {"wordCharsFields": 4, "wordBoolFields": 6, "wordCharsBoolCombinations": 1024,
                                 "wordLineValues": [0, 50, 100, 200], "wordTextScaleValues": [80, 100, 120],
                                 "permissionMarkers": ["permStart", "permEnd"],
                                 "slideAlignments": ["l", "ctr", "r", "just", "dist", "justLow", "thaiDist"],
                                 "slideBoolCombinations": 8, "lineSpacingUnits": ["pct", "pts"],
                                 "textDirections": ["horz", "vert", "vert270", "eaVert"],
                                 "sheetFeatures": ["shared-background", "filled-cells", "no-gridlines", "multi-page", "repeated-titles"],
                                 "imageFixtures": ["valid-png", "invalid-png"]},
                "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (DEST / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated {len(files)} files; manifest sha256={hashlib.sha256((DEST / 'manifest.json').read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
