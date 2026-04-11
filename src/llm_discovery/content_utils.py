"""Shared content validation utilities.

Used by prep_db.py and preflight_check.py.
"""

import hashlib
from pathlib import Path

# Content validation thresholds
MIN_CONTENT_LENGTH = 100
MIN_PRINTABLE_RATIO = 0.85

# Binary file magic bytes (at start of content body)
BINARY_MAGIC: dict[bytes, str] = {
    b"PK": "ZIP archive",
    b"Rar!": "RAR archive",
    b"7z\xbc\xaf": "7-Zip archive",
    b"MZ": "DOS/Windows EXE",
    b"\x7fELF": "Linux ELF binary",
    b"RIFF": "AVI/WAV container",
    b"CWS": "Compressed SWF (Flash)",
    b"FWS": "Uncompressed SWF (Flash)",
    b"OggS": "Ogg container",
    b"fLaC": "FLAC audio",
    b"ID3": "MP3 with ID3 tag",
    b"\xff\xfb": "MP3 audio",
    b"GIF87a": "GIF image",
    b"GIF89a": "GIF image",
    b"\x89PNG": "PNG image",
    b"\xff\xd8\xff": "JPEG image",
    b"BM": "BMP image",
    b"%PDF": "PDF document",
    b"\xd0\xcf\x11\xe0": "MS Office (old)",
    b"PK\x03\x04": "MS Office (new)/EPUB",
}


def get_content_body(content: str) -> str:
    """Extract body after URL header line."""
    if "\n\n" in content:
        return content.split("\n\n", 1)[1]
    return content


def is_binary_content(content: str) -> tuple[bool, str]:
    """Check if content starts with binary magic bytes."""
    body = get_content_body(content)
    if not body:
        return False, ""
    body_bytes = body[:10].encode("utf-8", errors="ignore")
    for magic, file_type in BINARY_MAGIC.items():
        if body_bytes.startswith(magic):
            return True, file_type
    return False, ""


def is_valid_text_content(content: str) -> tuple[bool, str]:
    """Check if content is valid text, not binary garbage."""
    if not content:
        return False, "empty content"
    body = get_content_body(content)
    if not body or len(body) < MIN_CONTENT_LENGTH:
        return False, f"content too short ({len(body) if body else 0} chars)"
    is_binary, binary_type = is_binary_content(content)
    if is_binary:
        return False, f"binary content detected ({binary_type})"
    if "\x00" in content:
        return False, "contains null bytes"
    printable = sum(1 for c in body if c.isprintable() or c in "\n\r\t")
    ratio = printable / len(body)
    if ratio < MIN_PRINTABLE_RATIO:
        return False, f"low printable ratio ({ratio:.1%})"
    return True, ""


def sha256_file(filepath: Path) -> str:
    """Calculate SHA-256 hash of file contents."""
    sha256 = hashlib.sha256()
    with filepath.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def sha256_string(content: str) -> str:
    """Calculate SHA-256 hash of string content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
