"""Tests for src/conversation/manager.py — trigger phrase detection."""

from src.conversation.manager import is_trigger_message


class TestIsTriggerMessage:
    # --- Positive cases ---
    def test_english_plan_dinner(self):
        assert is_trigger_message("plan dinner") is True

    def test_dutch_plan_eten(self):
        assert is_trigger_message("plan eten") is True

    def test_wat_eten_we(self):
        assert is_trigger_message("wat eten we") is True

    def test_meal_plan(self):
        assert is_trigger_message("meal plan") is True

    def test_boodschappen(self):
        assert is_trigger_message("boodschappen") is True

    def test_start_planning(self):
        assert is_trigger_message("start planning") is True

    def test_weekmenu(self):
        assert is_trigger_message("weekmenu") is True

    def test_whats_for_dinner(self):
        assert is_trigger_message("what's for dinner") is True

    def test_what_are_we_eating(self):
        assert is_trigger_message("what are we eating") is True

    # --- Case insensitivity ---
    def test_uppercase(self):
        assert is_trigger_message("PLAN DINNER") is True

    def test_mixed_case(self):
        assert is_trigger_message("Plan Eten") is True

    # --- Surrounding text ---
    def test_phrase_in_sentence(self):
        assert is_trigger_message("Hey, can you plan dinner for us?") is True

    def test_with_leading_whitespace(self):
        assert is_trigger_message("  plan dinner  ") is True

    # --- Negative cases ---
    def test_unrelated_message(self):
        assert is_trigger_message("How are you?") is False

    def test_partial_match(self):
        assert is_trigger_message("plan") is False

    def test_empty_string(self):
        assert is_trigger_message("") is False

    def test_dinner_without_plan(self):
        assert is_trigger_message("dinner was great") is False
