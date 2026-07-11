"""Literal false-positive tripwire for the WEBCHILD document-discovery paper.

Axis 2 asks a narrow, honest question about the model's *positive* verdicts: when
gpt-oss-120b marks a document as belonging to a category and cites evidence for
it, does that evidence contain the surface property the category is defined by?

This only makes sense for categories whose defining feature *is* a surface
property -- a question mark, a kinship word, a first-person-plural marker, a
gendered term of address, an age. For those, a deliberately broad *necessary
condition* captures the defining feature, and a positive verdict whose every
cited quote fails that condition is a candidate false positive. The condition is
broad on purpose: failing it should mean "this cannot be the category", not "the
model generalised past our examples". Because there is no gold standard, the tool
computes no error rate -- it shrinks the corpus to a small, readable pile of
candidate errors that a person then reads.

The word-based conditions (family, inclusive-we, gendered address) are
corpus-grounded: their vocabularies were mined from the surface forms actually
present in this multilingual corpus and curated by meaning, so that a form is
included only when it genuinely denotes the category's feature -- never because
the model cited it. Inclusive-we additionally uses verb-ending patterns for the
pro-drop languages (Spanish/Portuguese/Italian) that mark "we" morphologically
rather than with a pronoun. The symbol-based conditions (a digit for age, a
question mark for questions) are language-universal by construction.

False negatives are not measured: there is no ground truth for them, and a
keyword baseline is far too noisy to stand in for one. Categories defined by open
example lists (hobbies, fandom, computer culture, ...) have no closed necessary
condition and are out of scope; their correctness rests on the expert loop.

The pure matcher is separated from the database iteration so it can be
property-tested without a database; see ``docs/axis2-literal-validation.md``.
"""

from __future__ import annotations

import hashlib
import heapq
import re
import sqlite3
import unicodedata
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Targeted Danish orthographic variants, folded symmetrically on specs and text
# so "Århus"/"Aarhus" and "år"/"aar" unify. Other accents are left intact: a hit
# must still correspond to a surface form the condition enumerated.
_DANISH_FOLD = str.maketrans({"å": "aa", "ø": "oe", "æ": "ae"})

# Scripts without word spaces (Hangul, kana, CJK); terms in these match as
# substrings because word-boundary logic does not apply.
_CJK = re.compile(r"[ᄀ-ᇿ㄰-㆏぀-ヿ一-鿿가-힣]")
_WS = re.compile(r"\s+")
# Markdown emphasis runs glue to adjacent words ("_We", "**_Do", "MY_MOTHER")
# and, since "_" is a word character, defeat word-boundary matching. Treat them
# as separators so an emphasised term still matches.
_MD_EMPH = re.compile(r"[*_~`]+")


@dataclass(frozen=True)
class PatternSpec:
    """A set of literal patterns matched against text.

    ``terms`` match on the normalised text (word boundaries for Latin scripts,
    substring for CJK, flexible whitespace for phrases). ``literals`` match as
    exact substrings for punctuation-bearing strings (``?``, emoticons) where
    boundaries are meaningless. ``regex_patterns`` run on the *original* text so
    case-sensitive patterns keep the real casing.
    """

    category_id: int
    category_name: str
    source_prompt: str
    terms: tuple[str, ...] = ()
    literals: tuple[str, ...] = ()
    regex_patterns: tuple[str, ...] = ()


def normalise_for_match(text: str) -> str:
    """NFC-compose, casefold, fold Danish digraphs, and unglue markdown emphasis."""
    folded = unicodedata.normalize("NFC", text).casefold().translate(_DANISH_FOLD)
    return _MD_EMPH.sub(" ", folded)


def _is_cjk(term: str) -> bool:
    return _CJK.search(term) is not None


@cache
def _term_regex(norm_term: str) -> re.Pattern[str]:
    """Word-boundary pattern for a normalised Latin term or phrase."""
    parts = [re.escape(w) for w in _WS.split(norm_term) if w]
    return re.compile(r"\b" + r"\s+".join(parts) + r"\b")


@cache
def _regex(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def _hits(spec: PatternSpec, original: str, normalised: str) -> list[str]:
    """Patterns that fire, given pre-derived text forms (the hot path)."""
    hits: list[str] = []
    for term in spec.terms:
        norm_term = normalise_for_match(term)
        if _is_cjk(term):
            if norm_term in normalised:
                hits.append(term)
        elif _term_regex(norm_term).search(normalised):
            hits.append(term)
    hits.extend(lit for lit in spec.literals if normalise_for_match(lit) in normalised)
    hits.extend(p for p in spec.regex_patterns if _regex(p).search(original))
    return hits


def spec_hits(spec: PatternSpec, text: str) -> list[str]:
    """Return the patterns that fire on ``text`` (empty if none)."""
    return _hits(spec, text, normalise_for_match(text))


def matches(spec: PatternSpec, text: str) -> bool:
    """True if any of the spec's patterns appears in ``text``."""
    return bool(spec_hits(spec, text))


# --- Necessary-condition vocabularies ----------------------------------------
# A positive verdict is a candidate false positive when none of its cited quotes
# satisfies its category's necessary condition. Each condition is a deliberately
# BROAD set: a quote failing it should be unable to belong to the category at all,
# not merely use a synonym the prompt omitted. The word lists below were mined
# from the surface forms actually present in this corpus's flagged quotes and
# curated by meaning; a form is here only if it genuinely denotes the category's
# defining feature.

_ANY_DIGIT = r"\d"

# Gendered terms of address across the corpus's main languages.
_GENDERED_TERMS = (
    # English
    "boy",
    "boys",
    "girl",
    "girls",
    "boyz",
    "girlz",
    "dude",
    "dudes",
    "dudette",
    "guy",
    "guys",
    "gal",
    "gals",
    "lad",
    "lads",
    "lass",
    "lassie",
    "bro",
    "sis",
    "homie",
    "homies",
    "fella",
    "fellas",
    "man",
    "men",
    "woman",
    "women",
    "sir",
    "madam",
    "ma'am",
    "miss",
    "mister",
    "mr",
    "mrs",
    "ms",
    "lady",
    "ladies",
    "gentleman",
    "gentlemen",
    "son",
    "daughter",
    "king",
    "queen",
    "prince",
    "princess",
    # Danish
    "dreng",
    "drenge",
    "pige",
    "piger",
    "tøs",
    "tøser",
    "tøz",
    "tøzer",
    "tøzzer",
    "tøzzzer",
    "mand",
    "kvinde",
    "herre",
    "dame",
    "frøken",
    "fyr",
    # Spanish
    "chico",
    "chica",
    "chicos",
    "chicas",
    "niño",
    "niña",
    "niños",
    "niñas",
    "hombre",
    "mujer",
    "señor",
    "señora",
    "señorita",
    "muchacho",
    "muchacha",
    # Portuguese
    "menino",
    "menina",
    "meninos",
    "meninas",
    "rapaz",
    "rapariga",
    "homem",
    "mulher",
    "senhor",
    "senhora",
    "garoto",
    "garota",
    # Catalan
    "noi",
    "noia",
    "nois",
    "noies",
    "nen",
    "nena",
    # Italian
    "ragazzo",
    "ragazza",
    "ragazzi",
    "ragazze",
    "uomo",
    "donna",
    "signore",
    "signora",
    "bambino",
    "bambina",
    # French
    "garçon",
    "garçons",
    "fille",
    "filles",
    "homme",
    "femme",
    "monsieur",
    "madame",
    "mademoiselle",
    # German
    "junge",
    "jungen",
    "mädchen",
    "mann",
    "frau",
    "herr",
    "mädels",
    # Korean
    "소년",
    "소녀",
    "남자",
    "여자",
)

# First-person-plural markers: pronouns and possessives across languages, plus
# verb-ending patterns for the pro-drop languages that carry "we" in morphology.
_INCLUSIVE_TERMS = (
    # English
    "we",
    "us",
    "our",
    "ours",
    "ourselves",
    "let's",
    "lets",
    "let us",
    # Danish / Norwegian
    "vi",
    "os",
    "oss",
    "vores",
    "vor",
    "vort",
    "vore",
    "vår",
    "vårt",
    "våre",
    "vart",
    # Spanish
    "nos",
    "nosotros",
    "nosotras",
    "nuestro",
    "nuestra",
    "nuestros",
    "nuestras",
    # Portuguese
    "nós",
    "ns",
    "nosso",
    "nossa",
    "nossos",
    "nossas",
    # French
    "nous",
    "notre",
    "nôtre",
    # Italian
    "noi",
    "nostro",
    "nostra",
    "nostri",
    "nostre",
    # German / Dutch
    "wir",
    "uns",
    "unser",
    "unsere",
    "wij",
    "ons",
    "onze",
    # Icelandic
    "við",
    "okkar",
    "okkur",
    # Korean
    "우리",
    "저희",
)
# Pro-drop first-person-plural verb endings: Spanish/Portuguese -mos (podemos,
# vamos, somos, temos) and Italian -iamo (siamo, andiamo). Broad by design.
_INCLUSIVE_MORPH = (r"(?i)\b\w{2,}mos\b", r"(?i)\b\w{2,}iamo\b")

# Kinship terms (specific members, per the prompt's exclusion of general
# "family"/"relatives") across the corpus's main languages.
_FAMILY_TERMS = (
    # English, including plural forms
    "mom",
    "moms",
    "mommy",
    "mommies",
    "mum",
    "mummy",
    "mama",
    "mother",
    "mothers",
    "dad",
    "dads",
    "daddy",
    "daddies",
    "papa",
    "father",
    "fathers",
    "sister",
    "sisters",
    "sis",
    "brother",
    "brothers",
    "bro",
    "sibling",
    "siblings",
    "aunt",
    "aunts",
    "auntie",
    "uncle",
    "uncles",
    "cousin",
    "cousins",
    "grandma",
    "grandmas",
    "grandmother",
    "grandmothers",
    "granny",
    "grandpa",
    "grandpas",
    "grandfather",
    "grandfathers",
    "grandad",
    "granddad",
    "grandparent",
    "grandparents",
    "parent",
    "parents",
    "son",
    "sons",
    "daughter",
    "daughters",
    "niece",
    "nieces",
    "nephew",
    "nephews",
    "stepmother",
    "stepfather",
    "stepsister",
    "stepbrother",
    "twin",
    "twins",
    # Danish / Norwegian
    "far",
    "mor",
    "mormor",
    "morfar",
    "farmor",
    "farfar",
    "bedstemor",
    "bedstefar",
    "bedsteforældre",
    "søster",
    "søstre",
    "bror",
    "brødre",
    "forældre",
    "moster",
    "faster",
    "onkel",
    "tante",
    "fætter",
    "kusine",
    "barnebarn",
    "søskende",
    "mamma",
    "pappa",
    "foreldre",
    "besteforeldre",
    "bestemor",
    "bestefar",
    # Spanish
    "padres",
    "madre",
    "madres",
    "padre",
    "mamá",
    "papá",
    "hermano",
    "hermana",
    "hermanos",
    "hermanas",
    "abuelo",
    "abuela",
    "abuelos",
    "abuelas",
    "tío",
    "tía",
    "tíos",
    "tías",
    "primo",
    "prima",
    "primos",
    "primas",
    "hijo",
    "hija",
    "hijos",
    "hijas",
    "nieto",
    "nieta",
    # Portuguese
    "mãe",
    "mães",
    "pai",
    "pais",
    "mamãe",
    "papai",
    "irmão",
    "irmã",
    "irmãos",
    "irmãs",
    "avó",
    "avô",
    "avós",
    "vovó",
    "vovô",
    "tio",
    "tia",
    "tios",
    "tias",
    "filho",
    "filha",
    "filhos",
    "filhas",
    "neto",
    "neta",
    # French
    "mère",
    "père",
    "maman",
    "frère",
    "sœur",
    "soeur",
    "frères",
    "sœurs",
    "oncle",
    "cousine",
    "grand-mère",
    "grand-père",
    "fils",
    "fille",
    # German / Italian
    "mutter",
    "vater",
    "eltern",
    "bruder",
    "schwester",
    "geschwister",
    "oma",
    "opa",
    "sohn",
    "tochter",
    "genitori",
    "fratello",
    "sorella",
    "nonna",
    "nonno",
    "figlio",
    "figlia",
    # Korean
    "엄마",
    "아빠",
    "어머니",
    "아버지",
    "형",
    "오빠",
    "누나",
    "언니",
    "동생",
    "형제",
    "자매",
    "삼촌",
    "이모",
    "고모",
    "사촌",
    "할머니",
    "할아버지",
    "부모님",
)

# Child/age words for the (looser) age conditions.
_AGE_CHILD_TERMS = (
    "kid",
    "kids",
    "child",
    "children",
    "childs",
    "boy",
    "boys",
    "girl",
    "girls",
    "baby",
    "babies",
    "infant",
    "infants",
    "toddler",
    "toddlers",
    "teen",
    "teens",
    "teenager",
    "teenagers",
    "youth",
    "youngster",
    "youngsters",
    "pupil",
    "pupils",
    "kindergarten",
    "preschool",
    "schoolchild",
    "minor",
    "minors",
    "son",
    "daughter",
    "age",
    "aged",
    "ages",
    "old",
    "gammel",
    "gamle",
    "birthday",
    "born",
    "barn",
    "børn",
    "dreng",
    "pige",
    "tøs",
    "unge",
    "아이",
    "아이들",
    "어린이",
    "살",
    "나이",
)

# Interrogative openers for questions; the ``?`` literal carries most languages.
_QUESTION_TERMS = (
    "who",
    "what",
    "when",
    "where",
    "why",
    "which",
    "whom",
    "whose",
    "how",
    "do you",
    "does",
    "did you",
    "are you",
    "is it",
    "can you",
    "could you",
    "would you",
    "will you",
    "have you",
    "what's",
    "who's",
    "where's",
    "how's",
    "hvad",
    "hvor",
    "hvordan",
    "hvorfor",
    "hvem",
    "hvilken",
    "hvilket",
    "kan du",
    "har du",
    "er du",
    "vil du",
    "skal du",
    "너는",
    "있니",
)

NECESSARY: dict[str, PatternSpec] = {
    spec.category_name: spec
    for spec in (
        PatternSpec(
            9,
            "gendered_direct_address",
            "09_gendered_direct_address.yaml",
            terms=_GENDERED_TERMS,
        ),
        PatternSpec(
            14,
            "question_forms",
            "14_question_forms.yaml",
            terms=_QUESTION_TERMS,
            literals=("?",),
        ),
        PatternSpec(
            15,
            "first_person_plural_inclusivity",
            "15_first_person_plural_inclusivity.yaml",
            terms=_INCLUSIVE_TERMS,
            regex_patterns=_INCLUSIVE_MORPH,
        ),
        PatternSpec(
            16,
            "family",
            "16_family.yaml",
            terms=_FAMILY_TERMS,
        ),
        PatternSpec(
            2,
            "explicit_age_child_references",
            "02_explicit_age_child_references.yaml",
            terms=_AGE_CHILD_TERMS,
            regex_patterns=(_ANY_DIGIT,),
        ),
        PatternSpec(
            8,
            "age_identity_claims",
            "08_age_identity_claims.yaml",
            terms=(
                "grade",
                "grader",
                "graders",
                "klasse",
                "age",
                "aged",
                "år",
                "alder",
                "학년",
                "나이",
                "살",
            ),
            regex_patterns=(_ANY_DIGIT,),
        ),
    )
}


# --- False-positive tripwire -------------------------------------------------


@dataclass
class FPCategory:
    """Candidate-false-positive tally for one checkable category."""

    category_id: int  # the prompt's canonical id (filename prefix)
    category_name: str
    flagged: int  # positive verdicts whose every cited quote fails the condition
    total: int  # positive (yes/maybe) verdicts
    no_quote: int  # flagged verdicts that cited no quote at all (a subset of flagged)
    samples: list[tuple[int, list[str]]]  # (result_id, the cited quotes that failed)

    @property
    def rate(self) -> float:
        return 100 * self.flagged / self.total if self.total else 0.0


@dataclass
class FPReport:
    """Candidate-false-positive tallies for a corpus database."""

    categories: list[FPCategory]

    def by_name(self, name: str) -> FPCategory:
        return next(c for c in self.categories if c.category_name == name)


@dataclass
class _Acc:
    """Mutable per-category accumulator used inside a worker."""

    flagged: int = 0
    total: int = 0
    no_quote: int = 0
    samples: list[tuple[int, tuple[int, list[str]]]] = field(default_factory=list)


def _sample_key(text: str) -> int:
    """Deterministic, process-stable hash for reservoir selection."""
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest())


def _keep[T](heap: list[tuple[int, T]], size: int, key: int, payload: T) -> None:
    """Retain the ``size`` payloads with the smallest keys (a fixed reservoir)."""
    item = (-key, payload)
    if len(heap) < size:
        heapq.heappush(heap, item)
    else:
        heapq.heappushpop(heap, item)


def _merge_samples[T](heaps: list[list[tuple[int, T]]], size: int) -> list[T]:
    """Combine per-worker reservoirs into the global smallest-key ``size``."""
    combined = [item for heap in heaps for item in heap]
    return [payload for _negkey, payload in heapq.nlargest(size, combined)]


def _ro_connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)


def _fp_range(
    db_path: Path, lo: int, hi: int, checkable: dict[int, str], sample_size: int
) -> dict[int, _Acc]:
    """Flag candidate false positives whose result_id is in [lo, hi).

    A positive (yes/maybe) verdict is flagged when none of its cited quotes
    satisfies the category's necessary condition -- including the degenerate case
    of a positive verdict that cited no quote at all.
    """
    conn = _ro_connect(db_path)
    accs = {cid: _Acc() for cid in checkable}

    quotes: dict[tuple[int, int], list[str]] = defaultdict(list)
    q_cursor = conn.execute(
        "SELECT result_id, category_id, blockquote FROM result_category_blockquote "
        "WHERE result_id >= ? AND result_id < ?",
        (lo, hi),
    )
    for rid, cid, blockquote in q_cursor:
        if cid in checkable:
            quotes[(rid, cid)].append(blockquote)

    v_cursor = conn.execute(
        "SELECT result_id, category_id FROM result_category "
        "WHERE match IN ('yes', 'maybe') AND result_id >= ? AND result_id < ?",
        (lo, hi),
    )
    for rid, cid in v_cursor:
        name = checkable.get(cid)
        if name is None:
            continue
        spec = NECESSARY[name]
        acc = accs[cid]
        acc.total += 1
        cited = quotes.get((rid, cid), [])
        if not any(matches(spec, q) for q in cited):
            acc.flagged += 1
            if not cited:
                acc.no_quote += 1
            _keep(acc.samples, sample_size, _sample_key(f"{cid}:{rid}"), (rid, cited))

    conn.close()
    return accs


def _fp_range_args(
    args: tuple[Path, int, int, dict[int, str], int],
) -> dict[int, _Acc]:
    return _fp_range(*args)


def flag_false_positives(
    db_path: Path, *, workers: int = 1, sample_size: int = 40
) -> FPReport:
    """Flag candidate false positives across the checkable categories.

    For each category with a necessary condition, every positive verdict whose
    cited evidence fails that condition is flagged. The result_id space is
    partitioned across processes; each verdict is independent.
    """
    conn = _ro_connect(db_path)
    db_cats = dict(conn.execute("SELECT category_id, category_name FROM category"))
    checkable = {cid: name for cid, name in db_cats.items() if name in NECESSARY}
    max_rid = conn.execute("SELECT COALESCE(MAX(result_id), 0) FROM result").fetchone()[
        0
    ]
    conn.close()

    if workers <= 1 or max_rid == 0:
        parts = [_fp_range(db_path, 1, max_rid + 1, checkable, sample_size)]
    else:
        chunks = workers * 8
        width = (max_rid // chunks) + 1
        jobs = [
            (db_path, i * width + 1, (i + 1) * width + 1, checkable, sample_size)
            for i in range(chunks)
        ]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            parts = list(pool.map(_fp_range_args, jobs))

    categories = [
        FPCategory(
            category_id=NECESSARY[name].category_id,
            category_name=name,
            flagged=sum(part[cid].flagged for part in parts),
            total=sum(part[cid].total for part in parts),
            no_quote=sum(part[cid].no_quote for part in parts),
            samples=_merge_samples([part[cid].samples for part in parts], sample_size),
        )
        for cid, name in checkable.items()
    ]
    categories.sort(key=lambda c: c.category_id)
    return FPReport(categories=categories)
