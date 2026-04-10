"""Fetch pipeline: download pages from Internet Archive Wayback Machine and convert to markdown."""

import os
import re
import tempfile
from pathlib import Path

import markdownify
import requests

DEFAULT_DEMO_URLS: list[str] = [
    "https://web.archive.org/web/20040701020553/http://www.kidlink.org:80/KIDFORUM/",
    "https://web.archive.org/web/20040701022600/http://www.kidlink.org:80/KIDPROJ/Capitals97/introductions.html",
    "https://web.archive.org/web/20040701031153/http://www.kidlink.org:80/KIDPROJ/MCC/mcc0539.html",
    "https://web.archive.org/web/20040630084635/http://www.kidlink.org:80/spanish/",
    "https://web.archive.org/web/19970404181846/http://www.kidpub.org:80/kidpub/kidpub-newest.html",
]

_IA_URL_PATTERN = re.compile(
    r"^https?://web\.archive\.org/web/(\d{14})/(.+)$"
)


def parse_ia_url(url: str) -> tuple[str, str]:
    """Parse an Internet Archive URL into (timestamp, original_url)."""
    m = _IA_URL_PATTERN.match(url)
    if not m:
        raise ValueError(
            f"Not a valid Internet Archive URL (expected "
            f"https://web.archive.org/web/{{timestamp}}/{{url}}): {url}"
        )
    return m.group(1), m.group(2)


def verify_snapshot(original_url: str, timestamp: str) -> bool:
    """Check CDX API to verify a Wayback snapshot exists for this URL and timestamp."""
    resp = requests.get(
        "http://web.archive.org/cdx/search/cdx",
        params={
            "url": original_url,
            "output": "json",
            "from": timestamp,
            "to": timestamp,
            "limit": "1",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    # CDX returns header row + data rows; empty result means no match
    return len(data) > 1


def download_html(original_url: str, timestamp: str) -> str:
    """Fetch original HTML from Wayback Machine via the id_ endpoint."""
    id_url = f"https://web.archive.org/web/{timestamp}id_/{original_url}"
    resp = requests.get(id_url, timeout=30)
    try:
        resp.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Failed to download {id_url}: {exc}") from exc

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type.lower() and "text" not in content_type.lower():
        raise RuntimeError(
            f"Unexpected content-type '{content_type}' for {id_url} "
            f"(expected HTML)"
        )
    return resp.text


def html_to_markdown(html: str) -> str:
    """Convert HTML to markdown using markdownify."""
    return markdownify.markdownify(html)


def make_filename(original_url: str) -> str:
    """Create a filesystem-safe, deterministic filename from a URL."""
    # Strip protocol
    name = re.sub(r"^https?://", "", original_url)
    # Replace unsafe characters
    name = re.sub(r"[/:?&=\\]", "_", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip trailing underscores
    name = name.strip("_")
    # Truncate to reasonable length
    if len(name) > 200:
        name = name[:200]
    return name + ".md"


def fetch_single(url: str, output_dir: Path) -> Path | None:
    """Fetch a single URL from Internet Archive and write as markdown.

    Returns the output path if a new file was created, or None if the file
    already existed (idempotent skip).
    """
    timestamp, original_url = parse_ia_url(url)
    filename = make_filename(original_url)
    output_path = output_dir / filename

    # Idempotency: skip if already fetched
    if output_path.exists():
        return None

    # Verify snapshot exists
    verify_snapshot(original_url, timestamp)

    # Download and convert
    html = download_html(original_url, timestamp)
    md = html_to_markdown(html)

    # Prepend header line
    content = f"{timestamp}/{original_url}\n\n{md}"

    # Atomic write: temp file then rename
    fd, tmp_path = tempfile.mkstemp(dir=output_dir, suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, output_path)
    except BaseException:
        # Clean up temp file on any error
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return output_path


def fetch_corpus(urls: list[str] | None, output_dir: Path) -> list[Path]:
    """Fetch all URLs and return list of newly created files.

    Uses DEFAULT_DEMO_URLS if urls is None. Continues on per-URL errors,
    raises RuntimeError at end summarising all failures.
    """
    if urls is None:
        urls = DEFAULT_DEMO_URLS

    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    failed: list[tuple[str, str]] = []

    for url in urls:
        try:
            result = fetch_single(url, output_dir)
            if result is not None:
                written.append(result)
        except Exception as exc:
            failed.append((url, str(exc)))

    if failed:
        summary = "\n".join(f"  - {url}: {err}" for url, err in failed)
        raise RuntimeError(f"Failed to fetch {len(failed)} URL(s):\n{summary}")

    return written
