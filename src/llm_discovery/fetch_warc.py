"""Fetch pipeline (WARC path): download WARC records and extract HTML.

Stub for future implementation. The intended workflow is:
  URL → CDX API lookup → WARC range request → warcio extraction → markdownify → .md

This replaces the current id_ endpoint shortcut in fetch.py with proper
WARC-based provenance, preserving the original WARC record as an archival
artifact alongside the extracted markdown.

See: ArchiveSpark pattern in the design plan glossary.
Reference implementation:
  https://github.com/helgeho/ArchiveSpark/blob/master/notebooks/Downloading_WARC_from_Wayback.ipynb
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def fetch_warc_single(url: str, output_dir: Path) -> Path | None:
    """Fetch a single URL via WARC download and extract to markdown.

    Not yet implemented. Will:
    1. Query CDX API for WARC filename + byte offset
    2. HTTP range request to download the WARC record
    3. Extract HTML via warcio.archiveiterator.ArchiveIterator
    4. Convert HTML to markdown via markdownify
    5. Write both .warc and .md to output_dir
    """
    raise NotImplementedError("WARC-based fetch not yet implemented — use fetch.py")
