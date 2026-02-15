"""Tests for src/planner/preference_engine.py — preference matching and formatting."""

from src.models import Preference
from src.planner.preference_engine import PreferenceEngine


# Access pure methods without a full instance.

def _find_matching(existing, detail, category):
    return PreferenceEngine._find_matching(None, existing, detail, category)


def _format_existing(prefs):
    return PreferenceEngine._format_existing(None, prefs)


def _pref(category, detail, confidence=0.5, member_id="m1", id=1):
    return Preference(
        member_id=member_id,
        category=category,
        detail=detail,
        confidence=confidence,
        id=id,
    )


# --- _find_matching ---

class TestFindMatching:
    def test_exact_match(self):
        existing = [_pref("likes", "pasta")]
        result = _find_matching(existing, "pasta", "likes")
        assert result is not None
        assert result.detail == "pasta"

    def test_substring_new_in_existing(self):
        """New detail 'fish' is substring of existing 'no fish'."""
        existing = [_pref("dislikes", "no fish")]
        result = _find_matching(existing, "fish", "dislikes")
        assert result is not None

    def test_substring_existing_in_new(self):
        """Existing 'pasta' is substring of new 'fresh pasta'."""
        existing = [_pref("likes", "pasta")]
        result = _find_matching(existing, "fresh pasta", "likes")
        assert result is not None

    def test_case_insensitive(self):
        existing = [_pref("likes", "Pasta Carbonara")]
        result = _find_matching(existing, "pasta carbonara", "likes")
        assert result is not None

    def test_wrong_category_no_match(self):
        existing = [_pref("likes", "pasta")]
        result = _find_matching(existing, "pasta", "dislikes")
        assert result is None

    def test_no_match(self):
        existing = [_pref("likes", "pasta")]
        result = _find_matching(existing, "sushi", "likes")
        assert result is None

    def test_empty_existing(self):
        result = _find_matching([], "pasta", "likes")
        assert result is None


# --- _format_existing ---

class TestFormatExisting:
    def test_formats_with_confidence(self):
        prefs = [_pref("likes", "pasta", confidence=0.7)]
        result = _format_existing(prefs)
        assert "likes: pasta" in result
        assert "[70%]" in result

    def test_full_confidence_no_bracket(self):
        prefs = [_pref("dislikes", "fish", confidence=1.0)]
        result = _format_existing(prefs)
        assert "dislikes: fish" in result
        assert "%" not in result

    def test_multiple_preferences(self):
        prefs = [
            _pref("likes", "pasta", confidence=0.8),
            _pref("allergy", "peanuts", confidence=1.0),
        ]
        result = _format_existing(prefs)
        lines = result.strip().split("\n")
        assert len(lines) == 2
        assert "pasta" in lines[0]
        assert "peanuts" in lines[1]

    def test_empty_list(self):
        assert _format_existing([]) == ""
