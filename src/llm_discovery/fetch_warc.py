"""Preserve Wayback raw-content responses as WARC records during fetch.

The Kidlink corpus discussed in the associated article was fetched through the
markdown-only path in February 2026.  WARC preservation is prospective
provenance for future fetches and a planned one-page trace demonstration; it
does not retroactively describe how that reported corpus was acquired.
"""

# pattern: Mixed (WARC and filesystem I/O with isolated text conversion)

import contextlib
import os
import tempfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import requests
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers
from warcio.archiveiterator import ArchiveIterator
from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

from llm_discovery.fetch import (
    html_to_markdown,
    make_filename,
    parse_ia_url,
    verify_snapshot,
)


def _warc_date(timestamp: str) -> str:
    """Convert a 14-digit Wayback timestamp to a WARC UTC timestamp."""
    captured_at = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    return captured_at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_warc_html(warc_path: Path) -> str:
    """Read and decode the HTTP payload from a WARC response record."""
    with warc_path.open("rb") as stream:
        record = next(ArchiveIterator(stream))
        payload = record.content_stream().read()

    headers = CaseInsensitiveDict(record.http_headers.headers)
    content_type = headers.get("content-type", "")
    if "html" not in content_type.lower() and "text" not in content_type.lower():
        raise RuntimeError(
            f"Unexpected content-type '{content_type}' in {warc_path} (expected HTML)"
        )

    response = requests.Response()
    response.headers = headers
    response.encoding = get_encoding_from_headers(headers)
    response._content = payload
    return response.text


def _write_markdown(path: Path, content: str) -> None:
    """Atomically write markdown using the legacy fetch path's encoding."""
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        Path(tmp_path).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()
        raise


def _write_warc(
    path: Path,
    response: requests.Response,
    original_url: str,
    timestamp: str,
) -> None:
    """Atomically preserve a complete HTTP response record."""
    http_headers = StatusAndHeaders(
        f"{response.status_code} {response.reason}",
        list(response.headers.items()),
        protocol="HTTP/1.1",
    )
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".warc.gz.tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            writer = WARCWriter(stream, gzip=True)
            record = writer.create_warc_record(
                original_url,
                "response",
                payload=BytesIO(response.content),
                http_headers=http_headers,
                warc_headers_dict={"WARC-Date": _warc_date(timestamp)},
            )
            writer.write_record(record)
        Path(tmp_path).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()
        raise


def fetch_warc_single(url: str, output_dir: Path) -> Path | None:
    """Fetch one Wayback capture and preserve its response as a WARC record."""
    timestamp, original_url = parse_ia_url(url)
    markdown_path = output_dir / make_filename(original_url)
    warc_path = markdown_path.with_suffix(".warc.gz")

    if markdown_path.exists() and warc_path.exists():
        return None

    if not verify_snapshot(original_url, timestamp):
        raise RuntimeError(
            f"No snapshot found in CDX for {original_url} at {timestamp}"
        )

    id_url = f"https://web.archive.org/web/{timestamp}id_/{original_url}"
    response = requests.get(id_url, timeout=30)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        raise RuntimeError(f"Failed to download {id_url}: {exc}") from exc

    _write_warc(warc_path, response, original_url, timestamp)

    html = _read_warc_html(warc_path)
    markdown = html_to_markdown(html)
    _write_markdown(markdown_path, f"{timestamp}/{original_url}\n\n{markdown}")

    return markdown_path
