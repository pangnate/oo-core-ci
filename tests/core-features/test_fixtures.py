from __future__ import annotations

import hashlib
import json
import posixpath
import re
import struct
import zlib
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def q(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}"


class Checks:
    def __init__(self) -> None:
        self.count = 0

    def that(self, condition: bool, message: str) -> None:
        self.count += 1
        if not condition:
            raise AssertionError(message)


def check_png(path: Path, checks: Checks, should_be_valid: bool) -> None:
    data = path.read_bytes()
    valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    pos, seen_iend = 8, False
    while valid and pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        name = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            valid = False
            break
        body = data[pos + 4:pos + 8 + length]
        crc = struct.unpack(">I", data[pos + 8 + length:end])[0]
        if zlib.crc32(body) & 0xffffffff != crc:
            valid = False
            break
        pos = end
        if name == b"IEND":
            seen_iend = True
            break
    valid = valid and seen_iend and pos == len(data)
    checks.that(valid is should_be_valid, f"PNG validity mismatch: {path.name}")


def check_zip(path: Path, required: set[str], checks: Checks) -> zipfile.ZipFile:
    checks.that(zipfile.is_zipfile(path), f"not an OOXML ZIP: {path.name}")
    archive = zipfile.ZipFile(path)
    checks.that(archive.testzip() is None, f"ZIP CRC failure: {path.name}")
    names = set(archive.namelist())
    checks.that(required <= names, f"missing package parts in {path.name}: {sorted(required - names)}")
    for name in names:
        if name.endswith(".xml") or name.endswith(".rels"):
            ET.fromstring(archive.read(name))
            checks.count += 1
    # Resolve every internal OPC relationship from its owning part.
    for rel_name in (name for name in names if name.endswith(".rels")):
        rel_root = ET.fromstring(archive.read(rel_name))
        if rel_name == "_rels/.rels":
            base = ""
        else:
            match = re.match(r"^(.*?)/_rels/[^/]+\.rels$", rel_name)
            if not match:
                checks.that(False, f"malformed relationship part path: {rel_name}")
                continue
            base = match.group(1)
        for rel in rel_root.findall(f"{{{PKG_REL}}}Relationship"):
            if rel.get("TargetMode") == "External":
                continue
            target = posixpath.normpath(posixpath.join(base, rel.get("Target", "")))
            checks.that(target in names, f"broken relationship in {rel_name}: {target}")
    return archive


def verify_fixtures(directory: Path, profile: dict) -> int:
    checks = Checks()
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks.that(manifest.get("schemaVersion") == 1, "unsupported fixture manifest schema")
    for name, expected in manifest["files"].items():
        path = directory / name
        checks.that(path.is_file(), f"fixture missing: {name}")
        checks.that(hashlib.sha256(path.read_bytes()).hexdigest() == expected, f"fixture hash mismatch: {name}")
    checks.that(manifest["sourceRoot"] == "D:/docservice/idp-all/idp-example/public/templates", "fixture provenance changed")

    docx = check_zip(directory / "word-core-features.docx", {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}, checks)
    word = ET.fromstring(docx.read("word/document.xml"))
    paragraphs = word.findall(f".//{q(W, 'p')}")
    matrix = [p for p in paragraphs if p.find(q(W, "pPr")) is not None and p.find(f"{q(W, 'pPr')}/{q(W, 'ind')}") is not None]
    checks.that(len(matrix) == 1024, "Word char/bool Cartesian matrix count changed")
    char_fields = ("leftChars", "rightChars", "firstLineChars", "hangingChars")
    bool_fields = ("kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN")
    checks.that(all(all(q(W, field) in matrix[0].find(q(W, "pPr")) .find(q(W, "ind")).attrib for field in char_fields) for _ in (0,)), "Word char fields missing")
    for field in char_fields:
        values = {p.find(f"{q(W, 'pPr')}/{q(W, 'ind')}").get(q(W, field)) for p in matrix}
        checks.that(values == {"0", "80"}, f"Word {field} lacks zero/nonzero values")
    for field in bool_fields:
        values = {p.find(f"{q(W, 'pPr')}/{q(W, field)}").get(q(W, "val")) for p in matrix}
        checks.that(values == {"0", "1"}, f"Word {field} lacks explicit false/true")
    jcs = {node.get(q(W, "val")) for node in word.findall(f".//{q(W, 'jc')}")}
    checks.that(jcs == {"left", "right", "center", "both", "distribute"}, "Word alignment matrix incomplete")
    spacings = word.findall(f".//{q(W, 'spacing')}")
    checks.that({n.get(q(W, "beforeLines")) for n in spacings} == {"0", "50", "100", "200"}, "Word beforeLines matrix incomplete")
    scales = {n.get(q(W, "val")) for n in word.findall(f".//{q(W, 'w')}")}
    checks.that(scales == {"80", "100", "120"}, "Word TextScale values incomplete")
    checks.that(len(word.findall(f".//{q(W, 'permStart')}")) == 2 and len(word.findall(f".//{q(W, 'permEnd')}")) == 2, "Word protection marker fixtures incomplete")

    permission_cases = check_zip(directory / "word-permission-spellings.docx", {"word/document.xml"}, checks)
    permission_doc = ET.fromstring(permission_cases.read("word/document.xml"))
    permission_values = [
        (node.get(q(W, "displacedByCustomXml")), node.get(q(W, "displacedbyCustomXml")))
        for node in permission_doc.findall(f".//{q(W, 'permStart')}")
    ]
    checks.that(permission_values == [
        (None, "legacy-only"),
        ("standard-only", None),
        ("standard-wins", "legacy-loses"),
        ("standard-wins", "legacy-loses"),
    ], "permission spelling/precedence cases incomplete")

    protected_docx = check_zip(directory / "word-protection-roundtrip.docx", {"word/document.xml", "word/settings.xml"}, checks)
    protection_doc = ET.fromstring(protected_docx.read("word/document.xml"))
    protection_settings = ET.fromstring(protected_docx.read("word/settings.xml"))
    protection_attrs = protection_settings.find(q(W, "documentProtection"))
    expected_protection_attrs = {
        "edit", "enforcement", "formatting", "algorithmName", "cryptAlgorithmClass",
        "cryptAlgorithmSid", "cryptAlgorithmType", "cryptProvider", "cryptProviderType",
        "cryptProviderTypeExt", "cryptProviderTypeExtSource", "algIdExt", "algIdExtSource",
        "hash", "salt", "cryptSpinCount", "hashValue", "saltValue", "spinCount",
    }
    checks.that(protection_attrs is not None, "Word documentProtection settings missing")
    checks.that(
        protection_attrs is not None and {name.rsplit("}", 1)[-1] for name in protection_attrs.attrib} == expected_protection_attrs,
        "Word documentProtection attribute matrix incomplete",
    )
    checks.that(protection_doc.find(f".//{q(W, 'formProt')}").get(q(W, "val")) == "1", "Word section formProt sample missing")

    vml_docx = check_zip(directory / "word-vml-ideographic.docx", {"word/document.xml"}, checks)
    vml_doc = ET.fromstring(vml_docx.read("word/document.xml"))
    vml_shapes = vml_doc.findall(".//{urn:schemas-microsoft-com:vml}shape")
    checks.that(len(vml_shapes) == 1 and "layout-flow:vertical-ideographic" in vml_shapes[0].get("style", ""), "VML ideographic direction sample missing")

    broken_image = check_zip(directory / "word-broken-image.docx", {"word/document.xml", "word/media/bad.png", "word/_rels/document.xml.rels"}, checks)
    broken_doc = ET.fromstring(broken_image.read("word/document.xml"))
    broken_rels = ET.fromstring(broken_image.read("word/_rels/document.xml.rels"))
    image_rel = next((rel for rel in broken_rels.findall(f"{{{PKG_REL}}}Relationship") if rel.get("Id") == "rIdPatchImage"), None)
    checks.that(broken_doc.find(f".//{q(A, 'blip')}").get(q(R, "embed")) == "rIdPatchImage", "broken-image drawing reference missing")
    checks.that(image_rel is not None and image_rel.get("Target") == "media/bad.png", "broken-image package relationship missing")
    checks.that(broken_image.read("word/media/bad.png") == (directory / "bad.png").read_bytes(), "broken-image payload changed")

    pptx = check_zip(directory / "slide-core-features.pptx", {"[Content_Types].xml", "ppt/presentation.xml", "ppt/slides/slide1.xml"}, checks)
    slide = ET.fromstring(pptx.read("ppt/slides/slide1.xml"))
    ppr = slide.findall(f".//{q(A, 'pPr')}")
    checks.that({n.get("algn") for n in ppr if n.get("algn") is not None} == {"l", "ctr", "r", "just", "dist", "justLow", "thaiDist"}, "Slide alignment values incomplete")
    bool_matrix = {(n.get("rtl"), n.get("eaLnBrk"), n.get("latinLnBrk")) for n in ppr if "rtl" in n.attrib}
    checks.that(len(bool_matrix) == 8, "Slide boolean matrix incomplete")
    line_units = {n.tag.rsplit("}", 1)[-1] for n in slide.findall(f".//{q(A, 'lnSpc')}/*")}
    checks.that(line_units == {"pct", "pts"}, "Slide line spacing units incomplete")
    directions = {n.get("vert") for n in slide.findall(f".//{q(A, 'bodyPr')}")}
    checks.that({"horz", "vert", "vert270", "eaVert"} <= directions, "Slide body directions incomplete")

    xlsx = check_zip(directory / "sheet-core-features.xlsx", {"[Content_Types].xml", "xl/workbook.xml", "xl/styles.xml"}, checks)
    workbook = ET.fromstring(xlsx.read("xl/workbook.xml"))
    sheets = workbook.findall(f".//{q(X, 'sheet')}")
    checks.that([s.get("name") for s in sheets] == ["SharedBackground", "FilledCells", "NoGridMultiPage", "RepeatedTitles"], "Sheet fixture set incomplete")
    workbook_rels = ET.fromstring(xlsx.read("xl/_rels/workbook.xml.rels"))
    rel_ids = [n.get("Id") for n in workbook_rels.findall(q(PKG_REL, "Relationship"))]
    checks.that(len(rel_ids) == len(set(rel_ids)), "duplicate XLSX relationship IDs")
    for idx in range(1, 5):
        xml = ET.fromstring(xlsx.read(f"xl/worksheets/sheet{idx}.xml"))
        checks.that(len(xml.findall(f".//{q(X, 'row')}")) == 150, f"sheet{idx} page-height data incomplete")
        checks.that(all(len(row.findall(q(X, "c"))) == 30 for row in xml.findall(f".//{q(X, 'row')}")), f"sheet{idx} page-width data incomplete")
        if idx in (1, 2):
            checks.that(xml.find(q(X, "picture")) is not None, f"sheet{idx} shared background missing")
        if idx == 2:
            checks.that(xml.find(f".//{q(X, 'c')}").get("s") == "1", "filled-cell style missing")
        if idx == 3:
            checks.that(xml.find(f".//{q(X, 'sheetView')}").get("showGridLines") == "0", "gridline-off fixture missing")
        if idx == 4:
            titles = workbook.find(q(X, "definedNames"))
            checks.that(titles is not None and "RepeatedTitles" in "".join(titles.itertext()), "repeated print titles missing")
    check_png(directory / "known.png", checks, True)
    check_png(directory / "bad.png", checks, False)
    checks.that(profile.get("core", {}).get("ref") is not None, "source profile Core identity absent")
    if checks.count <= 0:
        raise AssertionError("fixture case made zero assertions")
    return checks.count
