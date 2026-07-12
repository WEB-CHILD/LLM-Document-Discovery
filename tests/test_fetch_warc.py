"""Tests for preserving Wayback responses as WARC before markdown conversion."""

from unittest.mock import patch, sentinel

import pytest
import requests
from warcio.archiveiterator import ArchiveIterator

from llm_discovery.fetch import fetch_corpus, fetch_single, make_filename
from llm_discovery.fetch_warc import fetch_warc_single

CAPTURE_URL = (
    "https://web.archive.org/web/20040701020553/"
    "http://www.kidlink.org:80/KIDFORUM/"
)
ORIGINAL_URL = "http://www.kidlink.org:80/KIDFORUM/"
PAYLOAD = b"<html><body><p>Kidlink \xc3\xa6ble</p></body></html>"


def _response(payload: bytes = PAYLOAD) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.reason = "OK"
    response.url = (
        "https://web.archive.org/web/20040701020553id_/" + ORIGINAL_URL
    )
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response._content = payload
    return response


@patch("llm_discovery.fetch_warc.verify_snapshot", return_value=True)
@patch("llm_discovery.fetch_warc.requests.get")
def test_written_warc_round_trips_exact_response_payload(
    mock_get, _mock_verify, tmp_path
):
    mock_get.return_value = _response()

    fetch_warc_single(CAPTURE_URL, tmp_path)

    markdown_path = tmp_path / make_filename(ORIGINAL_URL)
    warc_path = markdown_path.with_suffix(".warc.gz")
    with warc_path.open("rb") as stream:
        record = next(ArchiveIterator(stream))
        recovered_payload = record.content_stream().read()

    assert recovered_payload == PAYLOAD
    mock_get.assert_called_once_with(
        "https://web.archive.org/web/20040701020553id_/" + ORIGINAL_URL,
        timeout=30,
    )


@patch("llm_discovery.fetch_warc.verify_snapshot", return_value=True)
@patch("llm_discovery.fetch_warc.requests.get")
def test_warc_identifies_original_target_and_capture_time(
    mock_get, _mock_verify, tmp_path
):
    mock_get.return_value = _response()

    fetch_warc_single(CAPTURE_URL, tmp_path)

    warc_path = (tmp_path / make_filename(ORIGINAL_URL)).with_suffix(".warc.gz")
    with warc_path.open("rb") as stream:
        record = next(ArchiveIterator(stream))

    assert record.rec_headers["WARC-Target-URI"] == ORIGINAL_URL
    assert record.rec_headers["WARC-Date"] == "2004-07-01T02:05:53Z"


@patch("llm_discovery.fetch_warc.verify_snapshot", return_value=True)
@patch("llm_discovery.fetch_warc.requests.get")
@patch("llm_discovery.fetch.verify_snapshot", return_value=True)
@patch("llm_discovery.fetch.download_html")
def test_warc_markdown_is_byte_identical_to_markdown_only_fetch(
    mock_download,
    _mock_markdown_verify,
    mock_get,
    _mock_warc_verify,
    tmp_path,
):
    response = _response()
    mock_get.return_value = response
    mock_download.return_value = response.text
    markdown_only_dir = tmp_path / "markdown-only"
    warc_dir = tmp_path / "warc"
    markdown_only_dir.mkdir()
    warc_dir.mkdir()

    expected_path = fetch_single(
        CAPTURE_URL, markdown_only_dir, preserve_warc=False
    )
    actual_path = fetch_warc_single(CAPTURE_URL, warc_dir)

    assert expected_path is not None
    assert actual_path is not None
    assert actual_path.read_bytes() == expected_path.read_bytes()


@patch("llm_discovery.fetch.verify_snapshot", return_value=False)
@patch("llm_discovery.fetch_warc.fetch_warc_single")
def test_fetch_single_preserves_warc_by_default(
    mock_warc_fetch, _mock_markdown_verify, tmp_path
):
    mock_warc_fetch.return_value = sentinel.markdown_path

    result = fetch_single(CAPTURE_URL, tmp_path)

    assert result is sentinel.markdown_path
    mock_warc_fetch.assert_called_once_with(CAPTURE_URL, tmp_path)


@patch("llm_discovery.fetch_warc.verify_snapshot")
@patch("llm_discovery.fetch_warc.requests.get")
def test_warc_fetch_skips_only_when_both_artifacts_exist(
    mock_get, mock_verify, tmp_path
):
    markdown_path = tmp_path / make_filename(ORIGINAL_URL)
    markdown_path.write_text("existing", encoding="utf-8")
    markdown_path.with_suffix(".warc.gz").write_bytes(b"existing")

    result = fetch_warc_single(CAPTURE_URL, tmp_path)

    assert result is None
    mock_verify.assert_not_called()
    mock_get.assert_not_called()


@patch("llm_discovery.fetch.fetch_single")
def test_fetch_corpus_forwards_explicit_markdown_only_flag(mock_fetch, tmp_path):
    mock_fetch.return_value = tmp_path / "page.md"

    fetch_corpus([CAPTURE_URL], tmp_path, preserve_warc=False)

    mock_fetch.assert_called_once_with(
        CAPTURE_URL, tmp_path, preserve_warc=False
    )


@patch(
    "llm_discovery.fetch_warc.WARCWriter.write_record",
    side_effect=OSError("disk full"),
)
@patch("llm_discovery.fetch_warc.verify_snapshot", return_value=True)
@patch("llm_discovery.fetch_warc.requests.get")
def test_failed_warc_write_leaves_no_partial_artifact(
    mock_get, _mock_verify, _mock_write, tmp_path
):
    mock_get.return_value = _response()

    with pytest.raises(OSError, match="disk full"):
        fetch_warc_single(CAPTURE_URL, tmp_path)

    assert list(tmp_path.iterdir()) == []
