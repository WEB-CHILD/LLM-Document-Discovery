"""Tests for unified_processor module (no GPU/network required)."""

import json

from llm_discovery.unified_processor import (
    build_request_body,
    extract_json_from_text,
    parse_custom_id,
    parse_response,
    save_result_to_file,
)


class TestBuildRequestBody:
    def test_produces_correct_shape(self):
        custom_id, body = build_request_body(
            result_id=1,
            category_id=2,
            content="Test document content",
            category_filename="02_explicit_age_child_references.yaml",
            system_prompt="You are a text extraction tool.",
            category_prompts={
                "02_explicit_age_child_references.yaml": "Extract age references."
            },
            model="test-model",
        )
        assert custom_id == "r1_c2"
        assert body["model"] == "test-model"
        assert body["temperature"] == 0.0
        assert len(body["messages"]) == 2
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["role"] == "user"
        assert "Test document content" in body["messages"][1]["content"]
        assert "Extract age references" in body["messages"][1]["content"]

    def test_custom_id_format(self):
        custom_id, _ = build_request_body(
            result_id=42,
            category_id=7,
            content="",
            category_filename="test.yaml",
            system_prompt="",
            category_prompts={},
            model="m",
        )
        assert custom_id == "r42_c7"


class TestParseCustomId:
    def test_valid_id(self):
        assert parse_custom_id("r1_c2") == (1, 2)
        assert parse_custom_id("r42_c7") == (42, 7)


class TestExtractJsonFromText:
    def test_extracts_json(self):
        text = 'Some reasoning.\n{"match": "yes", "blockquotes": ["quote"]}'
        result = extract_json_from_text(text)
        assert result == {"match": "yes", "blockquotes": ["quote"]}

    def test_returns_none_for_no_json(self):
        assert extract_json_from_text("no json here") is None

    def test_handles_nested_braces(self):
        text = '{"match": "no", "nested": {"key": "val"}}'
        result = extract_json_from_text(text)
        assert result["match"] == "no"


class TestParseResponse:
    def test_valid_response(self):
        response = {
            "choices": [
                {
                    "message": {
                        "content": '{"match": "yes", "blockquotes": ["quote1"]}',
                    },
                }
            ],
        }
        parsed, error = parse_response("r1_c2", response, None)
        assert error is None
        assert parsed["result_id"] == 1
        assert parsed["category_id"] == 2
        assert parsed["match"] == "yes"
        assert parsed["blockquotes"] == ["quote1"]

    def test_error_response(self):
        parsed, error = parse_response("r1_c2", None, "HTTP 500")
        assert parsed is None
        assert "HTTP" in error

    def test_no_json_in_content(self):
        response = {"choices": [{"message": {"content": "no json here"}}]}
        parsed, error = parse_response("r1_c2", response, None)
        assert parsed is None
        assert "No JSON" in error

    def test_missing_match_field(self):
        response = {"choices": [{"message": {"content": '{"blockquotes": []}'}}]}
        parsed, error = parse_response("r1_c2", response, None)
        assert parsed is None
        assert "match" in error


class TestSaveResultToFile:
    def test_atomic_write(self, tmp_path):
        parsed = {
            "result_id": 1,
            "category_id": 2,
            "match": "yes",
            "blockquotes": ["test"],
        }
        saved = save_result_to_file(parsed, tmp_path)
        assert saved is True
        assert (tmp_path / "r1_c2.json").exists()

        data = json.loads((tmp_path / "r1_c2.json").read_text())
        assert data["match"] == "yes"

    def test_idempotent_skip(self, tmp_path):
        parsed = {"result_id": 1, "category_id": 2, "match": "no", "blockquotes": []}
        save_result_to_file(parsed, tmp_path)
        saved = save_result_to_file(parsed, tmp_path)
        assert saved is False
