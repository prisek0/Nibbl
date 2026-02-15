"""Tests for src/utils.py — JSON parsing from Claude responses."""

import pytest

from src.utils import parse_json_response


class TestParseJsonResponse:
    def test_plain_json_object(self):
        assert parse_json_response('{"key": "value"}') == {"key": "value"}

    def test_plain_json_array(self):
        assert parse_json_response('["a", "b"]') == ["a", "b"]

    def test_json_with_code_fence(self):
        text = '```json\n{"key": "value"}\n```'
        assert parse_json_response(text) == {"key": "value"}

    def test_json_with_bare_code_fence(self):
        text = '```\n{"key": "value"}\n```'
        assert parse_json_response(text) == {"key": "value"}

    def test_surrounding_whitespace(self):
        assert parse_json_response('  \n {"a": 1} \n  ') == {"a": 1}

    def test_code_fence_with_surrounding_text(self):
        text = 'Here is the result:\n```json\n{"plan": []}\n```\nDone.'
        assert parse_json_response(text) == {"plan": []}

    def test_nested_object(self):
        text = '{"plan": [{"recipe": {"name": "Pasta"}}]}'
        result = parse_json_response(text)
        assert result["plan"][0]["recipe"]["name"] == "Pasta"

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            parse_json_response("not json at all")

    def test_empty_object(self):
        assert parse_json_response("{}") == {}

    def test_empty_array(self):
        assert parse_json_response("[]") == []
