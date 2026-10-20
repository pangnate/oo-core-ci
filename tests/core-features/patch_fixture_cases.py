"""Generate focused OOXML inputs for regressions carried by Core patches."""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
V = "urn:schemas-microsoft-com:vml"

for prefix, namespace in (("w", W), ("r", R), ("wp", WP), ("a", A), ("pic", PIC), ("v", V)):
    ET.register_namespace(prefix, namespace)


def q(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def write_docx(template: Path, destination: Path, document: ET.Element, extra_parts: dict[str, bytes] | None = None,
               *, settings: ET.Element | None = None, image: bytes | None = None) -> None:
    replacements: dict[str, bytes] = {
        "word/document.xml": ET.tostring(document, encoding="utf-8", xml_declaration=True),
    }
    if settings is not None:
        replacements["word/settings.xml"] = ET.tostring(settings, encoding="utf-8", xml_declaration=True)
    if image is not None:
        replacements["word/media/bad.png"] = image
    if extra_parts:
        replacements.update(extra_parts)

    with zipfile.ZipFile(template) as source:
        rels = ET.fromstring(source.read("_rels/.rels"))
        document_rels_name = "word/_rels/document.xml.rels"
        if document_rels_name in source.namelist():
            document_rels = ET.fromstring(source.read(document_rels_name))
        else:
            document_rels = ET.Element(q(PKG_REL, "Relationships"))
        content_types = ET.fromstring(source.read("[Content_Types].xml"))

        def add_relation(rel_type: str, target: str, rel_id: str) -> None:
            ET.SubElement(document_rels, q(PKG_REL, "Relationship"), {
                "Id": rel_id, "Type": rel_type, "Target": target,
            })

        if settings is not None:
            add_relation(
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings",
                "settings.xml", "rIdPatchSettings",
            )
            ET.SubElement(content_types, q(CT, "Override"), {
                "PartName": "/word/settings.xml",
                "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml",
            })
        if image is not None:
            add_relation(
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                "media/bad.png", "rIdPatchImage",
            )
            if not any(node.get("Extension") == "png" for node in content_types.findall(q(CT, "Default"))):
                ET.SubElement(content_types, q(CT, "Default"), {"Extension": "png", "ContentType": "image/png"})
        replacements[document_rels_name] = ET.tostring(document_rels, encoding="utf-8", xml_declaration=True)
        replacements["[Content_Types].xml"] = ET.tostring(content_types, encoding="utf-8", xml_declaration=True)

        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as output:
            for item in source.infolist():
                payload = replacements.pop(item.filename, source.read(item.filename))
                output.writestr(item, payload)
            for name, payload in replacements.items():
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                output.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def paragraph(document: ET.Element, text: str) -> ET.Element:
    body = ET.SubElement(document, q(W, "body"))
    p = ET.SubElement(body, q(W, "p"))
    run = ET.SubElement(p, q(W, "r"))
    ET.SubElement(run, q(W, "t")).text = text
    return body


def make_permission_document() -> ET.Element:
    root = ET.Element(q(W, "document"))
    body = paragraph(root, "permission spelling regression")
    cases = (
        ("legacy-only", {"w:displacedbyCustomXml": "legacy-only"}),
        ("standard-only", {"w:displacedByCustomXml": "standard-only"}),
        ("standard-first", {"w:displacedByCustomXml": "standard-wins", "w:displacedbyCustomXml": "legacy-loses"}),
        ("legacy-first", {"w:displacedbyCustomXml": "legacy-loses", "w:displacedByCustomXml": "standard-wins"}),
    )
    for index, (label, attrs) in enumerate(cases, start=1):
        p = ET.SubElement(body, q(W, "p"))
        ET.SubElement(p, q(W, "permStart"), {q(W, "id"): str(index), **{q(W, key[2:]): value for key, value in attrs.items()}})
        run = ET.SubElement(p, q(W, "r"))
        ET.SubElement(run, q(W, "t")).text = label
        ET.SubElement(p, q(W, "permEnd"), {q(W, "id"): str(index)})
    ET.SubElement(body, q(W, "sectPr"))
    return root


def make_protection_document() -> tuple[ET.Element, ET.Element]:
    root = ET.Element(q(W, "document"))
    body = paragraph(root, "protection settings regression")
    sect = ET.SubElement(body, q(W, "sectPr"))
    ET.SubElement(sect, q(W, "formProt"), {q(W, "val"): "1"})
    settings = ET.Element(q(W, "settings"))
    attrs = {
        q(W, "edit"): "forms", q(W, "enforcement"): "1", q(W, "formatting"): "1",
        q(W, "algorithmName"): "SHA-256", q(W, "cryptAlgorithmClass"): "hash",
        q(W, "cryptAlgorithmSid"): "12", q(W, "cryptAlgorithmType"): "typeAny",
        q(W, "cryptProvider"): "rsaAES", q(W, "cryptProviderType"): "rsaAES",
        q(W, "cryptProviderTypeExt"): "provider-ext", q(W, "cryptProviderTypeExtSource"): "source-ext",
        q(W, "algIdExt"): "algorithm-ext", q(W, "algIdExtSource"): "algorithm-source",
        q(W, "hash"): "hash-legacy", q(W, "salt"): "salt-legacy", q(W, "cryptSpinCount"): "1000",
        q(W, "hashValue"): "hash-value", q(W, "saltValue"): "salt-value", q(W, "spinCount"): "2000",
    }
    ET.SubElement(settings, q(W, "documentProtection"), attrs)
    return root, settings


def make_vml_document() -> ET.Element:
    root = ET.Element(q(W, "document"))
    body = paragraph(root, "VML ideographic direction regression")
    p = ET.SubElement(body, q(W, "p"))
    pict = ET.SubElement(p, q(W, "pict"))
    shape = ET.SubElement(pict, q(V, "shape"), {
        "id": "vml-ideographic", "style": "width:120pt;height:60pt;layout-flow:vertical-ideographic",
        "type": "#_x0000_t202",
    })
    textbox = ET.SubElement(shape, q(V, "textbox"))
    content = ET.SubElement(textbox, q(W, "txbxContent"))
    p2 = ET.SubElement(content, q(W, "p"))
    run = ET.SubElement(p2, q(W, "r"))
    ET.SubElement(run, q(W, "t")).text = "縦書き"
    ET.SubElement(body, q(W, "sectPr"))
    return root


def make_broken_image_document() -> ET.Element:
    root = ET.Element(q(W, "document"))
    body = ET.SubElement(root, q(W, "body"))
    p = ET.SubElement(body, q(W, "p"))
    run = ET.SubElement(p, q(W, "r"))
    drawing = ET.SubElement(run, q(W, "drawing"))
    inline = ET.SubElement(drawing, q(WP, "inline"), {"distT": "0", "distB": "0", "distL": "0", "distR": "0"})
    ET.SubElement(inline, q(WP, "extent"), {"cx": "914400", "cy": "914400"})
    ET.SubElement(inline, q(WP, "docPr"), {"id": "1", "name": "Broken image"})
    frame = ET.SubElement(inline, q(WP, "cNvGraphicFramePr"))
    ET.SubElement(frame, q(A, "graphicFrameLocks"), {"noChangeAspect": "1"})
    graphic = ET.SubElement(inline, q(A, "graphic"))
    graphic_data = ET.SubElement(graphic, q(A, "graphicData"), {"uri": PIC})
    pic = ET.SubElement(graphic_data, q(PIC, "pic"))
    nv = ET.SubElement(pic, q(PIC, "nvPicPr"))
    ET.SubElement(nv, q(PIC, "cNvPr"), {"id": "0", "name": "Broken image"})
    ET.SubElement(nv, q(PIC, "cNvPicPr"))
    fill = ET.SubElement(pic, q(PIC, "blipFill"))
    ET.SubElement(fill, q(A, "blip"), {q(R, "embed"): "rIdPatchImage"})
    stretch = ET.SubElement(fill, q(A, "stretch"))
    ET.SubElement(stretch, q(A, "fillRect"))
    shape = ET.SubElement(pic, q(PIC, "spPr"))
    xfrm = ET.SubElement(shape, q(A, "xfrm"))
    ET.SubElement(xfrm, q(A, "off"), {"x": "0", "y": "0"})
    ET.SubElement(xfrm, q(A, "ext"), {"cx": "914400", "cy": "914400"})
    geom = ET.SubElement(shape, q(A, "prstGeom"), {"prst": "rect"})
    ET.SubElement(geom, q(A, "avLst"))
    ET.SubElement(body, q(W, "sectPr"))
    return root


def generate_patch_fixtures(destination: Path) -> list[str]:
    template = destination / "source-blank.docx"
    if not template.is_file():
        raise SystemExit(f"product source template missing: {template}")
    image = (destination / "bad.png").read_bytes()
    permission = "word-permission-spellings.docx"
    write_docx(template, destination / permission, make_permission_document())
    protected, settings = make_protection_document()
    protection = "word-protection-roundtrip.docx"
    write_docx(template, destination / protection, protected, settings=settings)
    vml = "word-vml-ideographic.docx"
    write_docx(template, destination / vml, make_vml_document())
    broken_image = "word-broken-image.docx"
    write_docx(template, destination / broken_image, make_broken_image_document(), image=image)
    return [permission, protection, vml, broken_image]
