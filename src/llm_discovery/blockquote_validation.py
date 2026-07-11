"""Block quote validation (faithfulness Axis 1).

Every blockquote the model returns should appear in the document it was drawn
from. Each quote is matched against its source with a whitespace- and
markdown-tolerant fuzzy match (rapidfuzz partial ratio). A quote below threshold
is re-checked with all formatting and encoding stripped, which separates a
presentation difference (``FORMATTING``) from text the model did not take from
the page (``GENUINE``).

The pure matching and classification functions are separated from the database
iteration (``verify_corpus``) so the classifier can be property-tested without a
database. Built for the validation section of the WEBCHILD document-discovery
paper; see ``docs/blockquote-validation.md``.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from pathlib import Path

ELLIPSIS = "[...]"
DEFAULT_THRESHOLD = 70.0
_RECOVERY_WORD_OVERLAP = 0.9

_WS = re.compile(r"\s+")
_MD_ESCAPE = re.compile(r"\\(['\[\]\\*_`~#>|!(){}+\-.])")
_WORD = re.compile(r"[0-9a-z]+")
_NONALNUM = re.compile(r"[^0-9a-z]+")
# NFKD leaves these joined letters intact; fold them explicitly.
_NORDIC = str.maketrans({"æ": "ae", "ø": "o", "å": "a", "œ": "oe", "ß": "ss"})


class Verdict(StrEnum):
    """How a blockquote relates to its source document."""

    EXACT = "exact"  # present verbatim (modulo whitespace and markdown escapes)
    FUZZY = "fuzzy"  # present within the fuzzy threshold
    FORMATTING = "formatting"  # below threshold; recovers once formatting stripped
    GENUINE = "genuine"  # absent even after stripping all formatting and encoding


def normalise(text: str) -> str:
    """Collapse whitespace and remove markdown backslash escapes for matching."""
    return _WS.sub(" ", _MD_ESCAPE.sub(r"\1", text)).strip()


def _fold(text: str) -> str:
    text = text.lower().translate(_NORDIC)
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def skeleton(text: str) -> str:
    """Reduce text to lowercase alphanumerics, dropping formatting and accents."""
    return _NONALNUM.sub("", _fold(text))


def words(text: str) -> list[str]:
    """Alphanumeric word tokens, lowercased and accent-folded."""
    return _WORD.findall(_fold(text))


def grounding_ratio(blockquote: str, normalised_source: str) -> float:
    """Best fuzzy match of the quote in the source, in [0, 100].

    Quotes may bridge omitted text with an ``[...]`` marker; each part must be
    found, so the score is the minimum over parts.
    """
    fragments = [n for f in blockquote.split(ELLIPSIS) if (n := normalise(f))]
    if not fragments:
        return 0.0
    # Exact substring is the common case and far cheaper than fuzzy alignment.
    return min(
        100.0 if f in normalised_source else fuzz.partial_ratio(f, normalised_source)
        for f in fragments
    )


def recovers_when_stripped(
    blockquote: str, source_skeleton: str, source_words: set[str]
) -> bool:
    """True if the quote's content survives once all formatting is removed.

    Either the quote's alphanumeric skeleton is a substring of the source's, or
    at least 90 per cent of its word tokens appear in the source.
    """
    bsk = skeleton(blockquote)
    if not bsk or bsk in source_skeleton:
        return True
    tokens = words(blockquote)
    if not tokens:
        return True
    present = sum(1 for w in tokens if w in source_words)
    return present / len(tokens) >= _RECOVERY_WORD_OVERLAP


def classify(
    blockquote: str,
    normalised_source: str,
    source_skeleton: str,
    source_words: set[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> Verdict:
    """Classify a quote against pre-derived source forms (the hot path)."""
    ratio = grounding_ratio(blockquote, normalised_source)
    if ratio >= 100:  # 100 is rapidfuzz's exact-match score
        return Verdict.EXACT
    if ratio >= threshold:
        return Verdict.FUZZY
    if recovers_when_stripped(blockquote, source_skeleton, source_words):
        return Verdict.FORMATTING
    return Verdict.GENUINE


def classify_blockquote(
    blockquote: str, source: str, threshold: float = DEFAULT_THRESHOLD
) -> Verdict:
    """Classify a single quote against a raw source document.

    Convenience wrapper that derives the matching forms; ``verify_corpus`` derives
    them once per document instead.
    """
    return classify(
        blockquote, normalise(source), skeleton(source), set(words(source)), threshold
    )


@dataclass
class CategoryReport:
    """Per-category verdict tally."""

    category_id: int
    category_name: str
    counts: Counter[str] = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def grounded(self) -> int:
        return self.counts[Verdict.EXACT] + self.counts[Verdict.FUZZY]

    @property
    def grounded_pct(self) -> float:
        return 100 * self.grounded / self.total if self.total else 0.0

    @property
    def genuine_pct(self) -> float:
        return 100 * self.counts[Verdict.GENUINE] / self.total if self.total else 0.0


@dataclass
class CorpusReport:
    """Verdict tallies for every category in a corpus database."""

    categories: list[CategoryReport]

    @property
    def total(self) -> int:
        return sum(c.total for c in self.categories)

    @property
    def grounded(self) -> int:
        return sum(c.grounded for c in self.categories)

    @property
    def genuine(self) -> int:
        return sum(c.counts[Verdict.GENUINE] for c in self.categories)


def _ro_connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)


def _verify_range(
    db_path: Path, lo: int, hi: int, threshold: float
) -> dict[int, Counter[str]]:
    """Classify every blockquote whose result_id is in [lo, hi).

    Streams ordered by result_id so each document's source forms are derived once.
    """
    conn = _ro_connect(db_path)
    out: dict[int, Counter[str]] = {}
    current_rid: int | None = None
    nsrc = ssk = ""
    swords: set[str] = set()
    cursor = conn.execute(
        "SELECT result_id, category_id, blockquote FROM result_category_blockquote "
        "WHERE result_id >= ? AND result_id < ? ORDER BY result_id",
        (lo, hi),
    )
    for rid, cid, blockquote in cursor:
        if rid != current_rid:
            row = conn.execute(
                "SELECT content FROM result WHERE result_id = ?", (rid,)
            ).fetchone()
            content = row[0] if row else ""
            nsrc = normalise(content)
            ssk = skeleton(content)
            swords = set(words(content))
            current_rid = rid
        verdict = classify(blockquote, nsrc, ssk, swords, threshold)
        out.setdefault(cid, Counter())[verdict] += 1
    conn.close()
    return out


def _verify_range_args(args: tuple[Path, int, int, float]) -> dict[int, Counter[str]]:
    return _verify_range(*args)


def verify_corpus(
    db_path: Path, *, threshold: float = DEFAULT_THRESHOLD, workers: int = 1
) -> CorpusReport:
    """Classify every stored blockquote against its source document.

    With ``workers > 1`` the result_id space is partitioned across processes; the
    work is embarrassingly parallel because each quote is independent.
    """
    conn = _ro_connect(db_path)
    cats = dict(conn.execute("SELECT category_id, category_name FROM category"))
    max_rid = conn.execute(
        "SELECT COALESCE(MAX(result_id), 0) FROM result"
    ).fetchone()[0]
    conn.close()

    if workers <= 1 or max_rid == 0:
        parts = [_verify_range(db_path, 1, max_rid + 1, threshold)]
    else:
        chunks = workers * 4
        width = (max_rid // chunks) + 1
        jobs = [
            (db_path, i * width + 1, (i + 1) * width + 1, threshold)
            for i in range(chunks)
        ]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            parts = list(pool.map(_verify_range_args, jobs))

    merged: dict[int, Counter[str]] = {}
    for part in parts:
        for cid, counts in part.items():
            merged.setdefault(cid, Counter()).update(counts)

    return CorpusReport(
        categories=[
            CategoryReport(cid, name, merged.get(cid, Counter()))
            for cid, name in sorted(cats.items())
        ]
    )
