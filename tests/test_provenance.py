"""Tests for the blockquote provenance verifier."""

import sqlite3

from llm_discovery.prep_db import sync_categories, sync_documents
from llm_discovery.provenance import (
    Verdict,
    classify_blockquote,
    grounding_ratio,
    normalise,
    recovers_when_stripped,
    skeleton,
    verify_corpus,
    words,
)

SOURCE = (
    "This is a forum for kids aged 10-15 to discuss topics. "
    "We love sharing ideas and making new friends. "
    "Vedligeholdt af Lærermenyu i København."
)


class TestNormalise:
    def test_collapses_whitespace(self):
        assert normalise("a   b\n\n c") == "a b c"

    def test_unescapes_markdown(self):
        assert normalise(r"Nevena \(11\), Yugoslavia") == "Nevena (11), Yugoslavia"


class TestSkeleton:
    def test_strips_formatting_and_case(self):
        assert skeleton("**Making, New_Friends!**") == "makingnewfriends"

    def test_folds_nordic_and_accents(self):
        assert skeleton("Lærermenyu København café") == "laerermenyukobenhavncafe"


class TestGroundingRatio:
    def test_exact_substring_scores_100(self):
        assert grounding_ratio("making new friends", normalise(SOURCE)) == 100

    def test_absent_text_scores_low(self):
        assert grounding_ratio("quarterly earnings exceeded", normalise(SOURCE)) < 70


class TestRecoversWhenStripped:
    def test_markdown_wrapped_real_text_recovers(self):
        ssk, sw = skeleton(SOURCE), set(words(SOURCE))
        assert recovers_when_stripped("**making new friends**", ssk, sw) is True

    def test_fabricated_text_does_not_recover(self):
        ssk, sw = skeleton(SOURCE), set(words(SOURCE))
        quote = "quarterly earnings exceeded forecasts"
        assert recovers_when_stripped(quote, ssk, sw) is False


class TestClassifyBlockquote:
    def test_verbatim_is_exact(self):
        assert classify_blockquote("making new friends", SOURCE) is Verdict.EXACT

    def test_whitespace_difference_is_grounded(self):
        v = classify_blockquote("making   new\nfriends", SOURCE)
        assert v in (Verdict.EXACT, Verdict.FUZZY)

    def test_minor_typo_is_fuzzy(self):
        quote = "we love sharing ideas and makin new freinds"
        assert classify_blockquote(quote, SOURCE) is Verdict.FUZZY

    def test_ellipsis_bridge_is_grounded(self):
        quote = "This is a forum for kids [...] making new friends"
        assert classify_blockquote(quote, SOURCE) in (Verdict.EXACT, Verdict.FUZZY)

    def test_formatting_only_difference_recovers(self):
        # Letter-spacing puts it below the fuzzy threshold, but the content is real.
        v = classify_blockquote("L a e r e r m e n y u", SOURCE)
        assert v in (Verdict.FUZZY, Verdict.FORMATTING)

    def test_fabrication_is_genuine(self):
        quote = "Quarterly earnings exceeded analyst forecasts."
        assert classify_blockquote(quote, SOURCE) is Verdict.GENUINE


class TestVerifyCorpus:
    def test_tallies_grounded_and_genuine_per_category(
        self, tmp_db, sample_corpus_dir, sample_prompts_dir
    ):
        sync_categories(tmp_db, sample_prompts_dir)
        sync_documents(tmp_db, sample_corpus_dir)

        conn = sqlite3.connect(tmp_db)
        rid = conn.execute(
            "SELECT result_id FROM result WHERE filepath LIKE '%doc1%'"
        ).fetchone()[0]
        insert = (
            "INSERT INTO result_category_blockquote "
            "(result_id, category_id, blockquote) VALUES (?, ?, ?)"
        )
        conn.executemany(
            insert,
            [
                (rid, 2, "making new friends"),
                (rid, 2, "Quarterly earnings exceeded analyst forecasts."),
            ],
        )
        conn.commit()
        conn.close()

        report = verify_corpus(tmp_db)
        cat2 = next(c for c in report.categories if c.category_id == 2)

        assert cat2.grounded == 1
        assert cat2.counts[Verdict.GENUINE] == 1
        assert report.total == 2
