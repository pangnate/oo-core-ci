"""Single source for the organization and four-part native binary version."""

from __future__ import annotations

import json
import re
from pathlib import Path

BRANDING_FILE = Path(__file__).resolve().parents[1] / "config" / "branding.json"


def load_branding() -> tuple[str, str, tuple[int, int, int, int]]:
    data = json.loads(BRANDING_FILE.read_text(encoding="utf-8"))
    organization = data["organization"]
    version = data["version"]
    if not isinstance(organization, str) or not re.fullmatch(r"[\x20-\x7e]+", organization):
        raise ValueError("branding organization must be non-empty ASCII for qmake")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise ValueError("branding version must have four numeric components")
    parts = tuple(int(part) for part in version.split("."))
    if any(part > 65535 for part in parts):
        raise ValueError("branding version components must fit in 16 bits")
    return organization, version, parts
