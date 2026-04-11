"""Tests for the fetch pipeline (Wayback Machine -> HTML -> markdown)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from llm_discovery.fetch import (
    DEFAULT_DEMO_URLS,
    download_html,
    fetch_corpus,
    fetch_single,
    html_to_markdown,
    make_filename,
    parse_ia_url,
    verify_snapshot,
)

# --- parse_ia_url ---


class TestParseIaUrl:
    def test_valid_url(self):
        ts, orig = parse_ia_url(
            "https://web.archive.org/web/20040701020553/http://www.kidlink.org:80/KIDFORUM/"
        )
        assert ts == "20040701020553"
        assert orig == "http://www.kidlink.org:80/KIDFORUM/"

    def test_valid_url_https_original(self):
        ts, orig = parse_ia_url(
            "https://web.archive.org/web/19970404181846/http://www.kidpub.org:80/kidpub/kidpub-newest.html"
        )
        assert ts == "19970404181846"
        assert orig == "http://www.kidpub.org:80/kidpub/kidpub-newest.html"

    def test_invalid_url_not_ia(self):
        with pytest.raises(ValueError, match="Internet Archive"):
            parse_ia_url("https://example.com/page")

    def test_invalid_url_missing_timestamp(self):
        with pytest.raises(ValueError):
            parse_ia_url("https://web.archive.org/web/")


# --- make_filename ---


class TestMakeFilename:
    def test_deterministic(self):
        url = "http://www.kidlink.org:80/KIDFORUM/"
        assert make_filename(url) == make_filename(url)

    def test_produces_md_extension(self):
        name = make_filename("http://www.kidlink.org:80/KIDFORUM/")
        assert name.endswith(".md")

    def test_filesystem_safe(self):
        name = make_filename("http://www.kidlink.org:80/KIDFORUM/?q=a&b=c")
        assert "/" not in name
        assert "\\" not in name
        assert ":" not in name


# --- html_to_markdown ---


class TestHtmlToMarkdown:
    def test_basic_conversion(self):
        html = "<h1>Hello</h1><p>World</p>"
        md = html_to_markdown(html)
        assert "Hello" in md
        assert "World" in md

    def test_preserves_links(self):
        html = '<a href="http://example.com">Link</a>'
        md = html_to_markdown(html)
        assert "Link" in md


# --- verify_snapshot (mocked) ---


class TestVerifySnapshot:
    @patch("llm_discovery.fetch.requests.get")
    def test_returns_true_when_snapshot_exists(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            ["urlkey", "timestamp", "original"],
            ["org,kidlink)/", "20040701020553", "http://www.kidlink.org:80/KIDFORUM/"],
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        assert verify_snapshot("http://www.kidlink.org:80/KIDFORUM/", "20040701020553") is True

    @patch("llm_discovery.fetch.requests.get")
    def test_returns_false_when_no_snapshot(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        assert verify_snapshot("http://example.com/nonexistent", "20990101000000") is False


# --- download_html (mocked) ---


class TestDownloadHtml:
    @patch("llm_discovery.fetch.requests.get")
    def test_returns_html(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>Hello</body></html>"
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        html = download_html("http://www.kidlink.org:80/KIDFORUM/", "20040701020553")
        assert "<body>" in html
        mock_get.assert_called_once_with(
            "https://web.archive.org/web/20040701020553id_/http://www.kidlink.org:80/KIDFORUM/",
            timeout=30,
        )

    @patch("llm_discovery.fetch.requests.get")
    def test_raises_on_http_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
        mock_get.return_value = mock_resp

        with pytest.raises(RuntimeError):
            download_html("http://example.com/missing", "20990101000000")


# --- fetch_single (mocked) ---


class TestFetchSingle:
    @patch("llm_discovery.fetch.download_html")
    @patch("llm_discovery.fetch.verify_snapshot", return_value=True)
    def test_creates_markdown_file_with_header(self, _mock_verify, mock_dl, tmp_path):
        mock_dl.return_value = "<html><body><p>Test content</p></body></html>"

        result = fetch_single(
            "https://web.archive.org/web/20040701020553/http://www.kidlink.org:80/KIDFORUM/",
            tmp_path,
        )
        assert result is not None
        assert result.exists()
        content = result.read_text()
        first_line = content.split("\n")[0]
        assert "20040701020553" in first_line
        assert "kidlink.org" in first_line

    @patch("llm_discovery.fetch.download_html")
    @patch("llm_discovery.fetch.verify_snapshot", return_value=True)
    def test_skips_existing_file(self, _mock_verify, mock_dl, tmp_path):
        url = "https://web.archive.org/web/20040701020553/http://www.kidlink.org:80/KIDFORUM/"
        # First fetch creates the file
        mock_dl.return_value = "<html><body><p>Content</p></body></html>"
        fetch_single(url, tmp_path)

        # Second fetch should skip (return None) without downloading
        mock_dl.reset_mock()
        result = fetch_single(url, tmp_path)
        assert result is None
        mock_dl.assert_not_called()

    @patch("llm_discovery.fetch.download_html")
    @patch("llm_discovery.fetch.verify_snapshot", return_value=True)
    def test_no_partial_files_on_error(self, _mock_verify, mock_dl, tmp_path):
        mock_dl.side_effect = RuntimeError("Network error")

        with pytest.raises(RuntimeError):
            fetch_single(
                "https://web.archive.org/web/20040701020553/http://www.kidlink.org:80/KIDFORUM/",
                tmp_path,
            )
        # No files should remain in output dir
        assert list(tmp_path.iterdir()) == []


# --- fetch_corpus (mocked) ---


class TestFetchCorpus:
    @patch("llm_discovery.fetch.fetch_single")
    def test_uses_default_urls_when_none(self, mock_single, tmp_path):
        mock_single.return_value = tmp_path / "test.md"
        fetch_corpus(None, tmp_path)
        assert mock_single.call_count == len(DEFAULT_DEMO_URLS)

    @patch("llm_discovery.fetch.fetch_single")
    def test_raises_on_failures(self, mock_single, tmp_path):
        mock_single.side_effect = RuntimeError("fail")
        with pytest.raises(RuntimeError, match="fail"):
            fetch_corpus(
                ["https://web.archive.org/web/20040701020553/http://www.kidlink.org:80/KIDFORUM/"],
                tmp_path,
            )

    @patch("llm_discovery.fetch.fetch_single")
    def test_returns_only_new_files(self, mock_single, tmp_path):
        # First call returns a path (new), second returns None (skipped)
        mock_single.side_effect = [tmp_path / "a.md", None]
        result = fetch_corpus(
            [
                "https://web.archive.org/web/20040701020553/http://www.kidlink.org:80/KIDFORUM/",
                "https://web.archive.org/web/20040701022600/http://www.kidlink.org:80/KIDPROJ/Capitals97/introductions.html",
            ],
            tmp_path,
        )
        assert len(result) == 1


# --- Integration tests (require network) ---


@pytest.mark.network
class TestFetchIntegration:
    """Integration tests that hit the live Internet Archive API."""

    KNOWN_GOOD_URL = "https://web.archive.org/web/20040701020553/http://www.kidlink.org:80/KIDFORUM/"

    def test_fetch_single_produces_valid_markdown(self, tmp_path):
        result = fetch_single(self.KNOWN_GOOD_URL, tmp_path)
        assert result is not None
        assert result.exists()

        content = result.read_text()
        first_line = content.split("\n")[0]
        # Header format: {timestamp}/{original_url}
        assert first_line.startswith("20040701020553/")
        assert "kidlink.org" in first_line

        # Content should be non-empty markdown with printable chars
        body = content[content.index("\n") :]
        assert len(body.strip()) > 0
        assert body.isprintable() or "\n" in body

    def test_idempotent_skip_on_rerun(self, tmp_path):
        # First run creates the file
        result1 = fetch_single(self.KNOWN_GOOD_URL, tmp_path)
        assert result1 is not None

        # Second run skips without HTTP request
        result2 = fetch_single(self.KNOWN_GOOD_URL, tmp_path)
        assert result2 is None
