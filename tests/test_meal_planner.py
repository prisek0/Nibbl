"""Tests for src/planner/meal_planner.py — pure parsing and formatting functions."""

from datetime import date

from src.models import FamilyMember, MemberRole
from src.planner.meal_planner import MealPlanner, _get_season


# We test the pure methods without instantiating MealPlanner (no API client needed).
# Access them as unbound methods or via a minimal instance.

def _parse_meal_plan(data):
    """Call _parse_meal_plan without needing a full MealPlanner instance."""
    return MealPlanner._parse_meal_plan(None, data)


def _format_wishes(wishes, members):
    return MealPlanner._format_wishes(None, wishes, members)


def _clean_message_history(messages):
    return MealPlanner._clean_message_history(None, messages)


# --- _get_season ---

class TestGetSeason:
    def test_winter_months(self):
        assert _get_season(12) == "winter"
        assert _get_season(1) == "winter"
        assert _get_season(2) == "winter"

    def test_spring_months(self):
        assert _get_season(3) == "lente"
        assert _get_season(5) == "lente"

    def test_summer_months(self):
        assert _get_season(6) == "zomer"
        assert _get_season(8) == "zomer"

    def test_autumn_months(self):
        assert _get_season(9) == "herfst"
        assert _get_season(11) == "herfst"


# --- _parse_meal_plan ---

class TestParseMealPlan:
    def test_parses_full_plan(self):
        data = {
            "reasoning": "Balanced meals",
            "plan": [
                {
                    "date": "2026-02-13",
                    "recipe": {
                        "name": "Pasta Carbonara",
                        "description": "Classic Roman pasta",
                        "servings": 4,
                        "prep_time_minutes": 10,
                        "cook_time_minutes": 20,
                        "cuisine": "Italian",
                        "tags": ["Italian", "quick"],
                        "ingredients": [
                            {"name": "spaghetti", "quantity": 500, "unit": "g", "category": "pantry"},
                            {"name": "pancetta", "quantity": 200, "unit": "g", "category": "meat"},
                        ],
                        "instructions": "1. Cook pasta\n2. Fry pancetta",
                    },
                }
            ],
        }
        plan = _parse_meal_plan(data)
        assert plan.reasoning == "Balanced meals"
        assert len(plan.recipes) == 1

        recipe = plan.recipes[0]
        assert recipe.name == "Pasta Carbonara"
        assert recipe.planned_date == date(2026, 2, 13)
        assert recipe.servings == 4
        assert recipe.cuisine == "Italian"
        assert len(recipe.ingredients) == 2
        assert recipe.ingredients[0].name == "spaghetti"
        assert recipe.ingredients[0].quantity == 500

    def test_missing_optional_fields_use_defaults(self):
        data = {
            "plan": [
                {
                    "date": "2026-02-13",
                    "recipe": {
                        "name": "Simple Dish",
                    },
                }
            ],
        }
        plan = _parse_meal_plan(data)
        recipe = plan.recipes[0]
        assert recipe.description == ""
        assert recipe.servings == 4
        assert recipe.prep_time_minutes == 0
        assert recipe.cook_time_minutes == 0
        assert recipe.cuisine == ""
        assert recipe.tags == []
        assert recipe.ingredients == []
        assert recipe.instructions == ""
        assert plan.reasoning == ""

    def test_empty_plan(self):
        plan = _parse_meal_plan({"plan": []})
        assert plan.recipes == []

    def test_multiple_recipes(self):
        data = {
            "plan": [
                {"date": "2026-02-13", "recipe": {"name": "Dish A"}},
                {"date": "2026-02-14", "recipe": {"name": "Dish B"}},
                {"date": "2026-02-15", "recipe": {"name": "Dish C"}},
            ]
        }
        plan = _parse_meal_plan(data)
        assert len(plan.recipes) == 3
        assert plan.recipes[1].planned_date == date(2026, 2, 14)


# --- _format_wishes ---

class TestFormatWishes:
    def test_formats_wishes(self):
        members = [
            FamilyMember(id="m1", name="Alice", imessage_id="+1", role=MemberRole.PARENT),
            FamilyMember(id="m2", name="Bob", imessage_id="+2", role=MemberRole.CHILD),
        ]
        wishes = {
            "m1": ["something Italian"],
            "m2": ["pizza", "no fish"],
        }
        result = _format_wishes(wishes, members)
        assert "Alice: something Italian" in result
        assert "Bob: pizza" in result
        assert "Bob: no fish" in result

    def test_empty_wishes(self):
        assert _format_wishes({}, []) == ""

    def test_unknown_member_id(self):
        wishes = {"unknown-id": ["pasta"]}
        result = _format_wishes(wishes, [])
        assert "Unknown: pasta" in result


# --- _clean_message_history ---

class TestCleanMessageHistory:
    def test_alternating_messages_unchanged(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "plan dinner"},
        ]
        result = _clean_message_history(messages)
        assert len(result) == 3
        assert result[0]["role"] == "user"

    def test_merges_consecutive_same_role(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "user", "content": "plan dinner"},
            {"role": "assistant", "content": "ok"},
        ]
        result = _clean_message_history(messages)
        assert len(result) == 2
        assert "hi\nplan dinner" in result[0]["content"]

    def test_strips_leading_assistant(self):
        messages = [
            {"role": "assistant", "content": "welcome"},
            {"role": "user", "content": "hi"},
        ]
        result = _clean_message_history(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_empty_list(self):
        assert _clean_message_history([]) == []

    def test_only_assistant_messages(self):
        messages = [{"role": "assistant", "content": "hello"}]
        result = _clean_message_history(messages)
        assert result == []
