"""Tests for the literal false-positive tripwire (faithfulness Axis 2).

The matcher decides whether a piece of text contains any of a set of patterns.
The tripwire uses it to flag positive verdicts whose cited evidence fails a
category's broad necessary condition -- candidate false positives for a human to
read. The checker is calibrated to the category's defining surface property,
never to agree with the model.
"""

import sqlite3

from llm_discovery.literal import (
    NECESSARY,
    PatternSpec,
    flag_false_positives,
    matches,
    normalise_for_match,
    spec_hits,
)
from llm_discovery.prep_db import sync_categories, sync_documents

CHECKABLE = {
    "gendered_direct_address",
    "question_forms",
    "first_person_plural_inclusivity",
    "family",
    "explicit_age_child_references",
    "age_identity_claims",
}


class TestNormaliseForMatch:
    def test_casefolds_and_keeps_other_accents(self):
        # General accents are preserved (surface-form matching, not folding).
        assert normalise_for_match("CAFÉ") == "café"

    def test_folds_targeted_danish_digraphs(self):
        assert normalise_for_match("Århus tøz lærer") == "aarhus toez laerer"

    def test_aa_spelling_unifies_with_ring(self):
        # The å↔aa fold is symmetric, so both spellings normalise alike.
        assert normalise_for_match("Aarhus") == normalise_for_match("Århus")


class TestTermMatching:
    def test_latin_term_respects_word_boundaries(self):
        spec = PatternSpec(99, "t", "t.yaml", terms=("old",))
        assert matches(spec, "I am very old now") is True
        assert matches(spec, "a gold ring") is False

    def test_cjk_term_matches_as_substring(self):
        # Korean has no word spaces, so boundary logic cannot apply.
        spec = PatternSpec(99, "t", "t.yaml", terms=("아이들",))
        assert matches(spec, "우리 아이들이 놀아요") is True
        assert matches(spec, "kids only here") is False

    def test_danish_variant_matches_both_spellings(self):
        spec = PatternSpec(99, "t", "t.yaml", terms=("år",))
        assert matches(spec, "han er 10 år gammel") is True
        assert matches(spec, "han er 10 aar gammel") is True

    def test_multiword_term_allows_flexible_whitespace(self):
        spec = PatternSpec(99, "t", "t.yaml", terms=("let us",))
        assert matches(spec, "so let  us\nbegin") is True
        assert matches(spec, "let the games begin") is False

    def test_spec_hits_reports_which_terms_fired(self):
        spec = PatternSpec(99, "t", "t.yaml", terms=("mom", "dad"))
        assert spec_hits(spec, "my mom is here") == ["mom"]

    def test_markdown_emphasis_does_not_block_boundary(self):
        # "_" is a word char, so emphasis runs would otherwise defeat \b.
        spec = PatternSpec(99, "t", "t.yaml", terms=("mother", "we"))
        assert matches(spec, "_Mother Earth_") is True
        assert matches(spec, "MY_MOTHER") is True
        assert matches(spec, "**_We leave old info_**") is True


class TestLiteralMatching:
    def test_question_mark_matches_without_word_boundary(self):
        spec = PatternSpec(99, "t", "t.yaml", literals=("?",))
        assert matches(spec, "really?") is True
        assert matches(spec, "a plain statement") is False

    def test_copyright_symbol_literal(self):
        spec = PatternSpec(99, "t", "t.yaml", literals=("©",))
        assert matches(spec, "Kidlink © 2001") is True


class TestRegexMatching:
    def test_any_digit(self):
        spec = PatternSpec(99, "t", "t.yaml", regex_patterns=(r"\d",))
        assert matches(spec, "he is 12") is True
        assert matches(spec, "no numbers here") is False


class TestNecessaryScope:
    def test_covers_exactly_the_six_checkable_categories(self):
        assert set(NECESSARY) == CHECKABLE

    def test_key_matches_spec_name_and_id_matches_filename_prefix(self):
        for name, spec in NECESSARY.items():
            assert spec.category_name == name
            assert spec.source_prompt.startswith(f"{spec.category_id:02d}_")


class TestNecessaryConditions:
    def _hit(self, name, text):
        return matches(NECESSARY[name], text)

    def test_family_requires_a_kinship_word(self):
        assert self._hit("family", "my grandmother came to visit")
        assert self._hit("family", "min mormor bor her")
        assert self._hit("family", "엄마 아빠")  # CJK
        assert not self._hit("family", "the weather forecast for today")

    def test_question_forms_require_mark_or_interrogative(self):
        assert self._hit("question_forms", "how are you today?")
        assert self._hit("question_forms", "what is your name")  # no mark
        assert not self._hit("question_forms", "this is a plain statement")

    def test_inclusive_requires_first_person_plural(self):
        assert self._hit("first_person_plural_inclusivity", "we can play together")
        assert self._hit("first_person_plural_inclusivity", "vi leger sammen")
        assert not self._hit(
            "first_person_plural_inclusivity", "the company sells widgets"
        )

    def test_gendered_requires_a_gendered_word(self):
        assert self._hit("gendered_direct_address", "hey boys and girls")
        assert self._hit("gendered_direct_address", "kom nu piger")
        assert not self._hit("gendered_direct_address", "the weather is nice")

    def test_age_child_requires_digit_or_child_word(self):
        assert self._hit("explicit_age_child_references", "he is 12 years old")
        assert self._hit("explicit_age_child_references", "a site for children")
        assert not self._hit("explicit_age_child_references", "quarterly revenue")

    def test_age_identity_requires_digit_or_grade_word(self):
        assert self._hit("age_identity_claims", "I am 12")
        assert self._hit("age_identity_claims", "she is in grade five")
        assert not self._hit("age_identity_claims", "hello world")


class TestFlagFalsePositives:
    def _seed(self, tmp_db, sample_corpus_dir, sample_prompts_dir):
        sync_categories(tmp_db, sample_prompts_dir)
        sync_documents(tmp_db, sample_corpus_dir)
        conn = sqlite3.connect(tmp_db)
        age_cat = conn.execute(
            "SELECT category_id FROM category "
            "WHERE category_name = 'explicit_age_child_references'"
        ).fetchone()[0]
        rids = {
            n: conn.execute(
                "SELECT result_id FROM result WHERE filepath LIKE ?", (f"%{n}%",)
            ).fetchone()[0]
            for n in ("doc1", "doc2", "doc3")
        }
        # Verdict A: supported (a cited quote contains a child word).
        conn.execute(
            "INSERT INTO result_category (result_id, category_id, match) "
            "VALUES (?, ?, 'yes')",
            (rids["doc1"], age_cat),
        )
        conn.execute(
            "INSERT INTO result_category_blockquote "
            "(result_id, category_id, blockquote) VALUES (?, ?, ?)",
            (rids["doc1"], age_cat, "this forum is for kids"),
        )
        # Verdict B: flagged (its only cited quote fails the condition).
        conn.execute(
            "INSERT INTO result_category (result_id, category_id, match) "
            "VALUES (?, ?, 'maybe')",
            (rids["doc2"], age_cat),
        )
        conn.execute(
            "INSERT INTO result_category_blockquote "
            "(result_id, category_id, blockquote) VALUES (?, ?, ?)",
            (rids["doc2"], age_cat, "the quarterly report is ready"),
        )
        # Verdict C: flagged (positive with no cited evidence at all).
        conn.execute(
            "INSERT INTO result_category (result_id, category_id, match) "
            "VALUES (?, ?, 'yes')",
            (rids["doc3"], age_cat),
        )
        conn.commit()
        conn.close()
        return rids

    def test_flags_unsupported_positives(
        self, tmp_db, sample_corpus_dir, sample_prompts_dir
    ):
        self._seed(tmp_db, sample_corpus_dir, sample_prompts_dir)
        report = flag_false_positives(tmp_db)
        cat = report.by_name("explicit_age_child_references")
        assert cat.total == 3
        assert cat.flagged == 2  # verdict B (bad quote) and verdict C (no quote)
        assert cat.no_quote == 1  # only verdict C cited nothing

    def test_sample_carries_the_failing_quotes(
        self, tmp_db, sample_corpus_dir, sample_prompts_dir
    ):
        self._seed(tmp_db, sample_corpus_dir, sample_prompts_dir)
        report = flag_false_positives(tmp_db)
        cat = report.by_name("explicit_age_child_references")
        sampled_quotes = [q for _rid, quotes in cat.samples for q in quotes]
        assert "the quarterly report is ready" in sampled_quotes

    def test_only_checkable_categories_reported(
        self, tmp_db, sample_corpus_dir, sample_prompts_dir
    ):
        self._seed(tmp_db, sample_corpus_dir, sample_prompts_dir)
        report = flag_false_positives(tmp_db)
        names = {c.category_name for c in report.categories}
        # sample_prompts_dir also defines 03 corporate, which is not checkable.
        assert names == {"explicit_age_child_references"}
