"""Tests for src/planner/formatter.py — iMessage formatting functions."""

from datetime import date

from src.models import CartReport, Ingredient, Recipe
from src.planner.formatter import (
    _l,
    format_cart_report,
    format_full_ingredient_list,
    format_meal_plan,
    format_pantry_check,
    format_recipe_detail,
)


def _ing(name, qty=0, unit="", category="other", optional=False):
    return Ingredient(name=name, quantity=qty, unit=unit, category=category, optional=optional)


def _recipe(name="Test Recipe", planned_date=date(2026, 2, 13), ingredients=None, **kwargs):
    defaults = dict(
        id="r1",
        name=name,
        description="A test recipe",
        planned_date=planned_date,
        servings=4,
        prep_time_minutes=10,
        cook_time_minutes=20,
        cuisine="Italian",
        tags=[],
        ingredients=ingredients or [],
        instructions="Cook it.",
    )
    defaults.update(kwargs)
    return Recipe(**defaults)


# --- Localization helper ---

class TestLocalization:
    def test_dutch_label(self):
        assert "menu" in _l("menu_header", "nl").lower() or "week" in _l("menu_header", "nl").lower()

    def test_english_label(self):
        assert "menu" in _l("menu_header", "en").lower()

    def test_unknown_key_returns_bracketed(self):
        assert _l("nonexistent_key", "en") == "[nonexistent_key]"

    def test_format_kwargs(self):
        result = _l("cart_added", "en", n=5)
        assert "5" in result


# --- format_meal_plan ---

class TestFormatMealPlan:
    def test_english_output(self):
        recipes = [
            _recipe(name="Pasta", planned_date=date(2026, 2, 13)),  # Friday
            _recipe(name="Curry", planned_date=date(2026, 2, 14)),  # Saturday
        ]
        result = format_meal_plan(recipes, lang="en")
        assert "Pasta" in result
        assert "Curry" in result
        assert "Fri" in result
        assert "Sat" in result

    def test_dutch_output(self):
        recipes = [_recipe(planned_date=date(2026, 2, 13))]  # Friday
        result = format_meal_plan(recipes, lang="nl")
        assert "Vr" in result

    def test_time_shown(self):
        recipes = [_recipe(prep_time_minutes=10, cook_time_minutes=20)]
        result = format_meal_plan(recipes, lang="en")
        assert "30 min" in result

    def test_no_time_when_zero(self):
        recipes = [_recipe(prep_time_minutes=0, cook_time_minutes=0)]
        result = format_meal_plan(recipes, lang="en")
        assert "min" not in result


# --- format_pantry_check ---

class TestFormatPantryCheck:
    def test_filters_pantry_and_spice(self):
        ingredients = [
            _ing("olijfolie", 2, "el", category="pantry"),
            _ing("komijn", 1, "tl", category="spice"),
            _ing("biefstuk", 500, "g", category="meat"),
        ]
        result = format_pantry_check(ingredients, lang="en")
        assert "olijfolie" in result
        assert "komijn" in result
        assert "biefstuk" not in result

    def test_skips_optional(self):
        ingredients = [_ing("truffle oil", 1, "el", category="pantry", optional=True)]
        result = format_pantry_check(ingredients, lang="en")
        assert result == ""

    def test_empty_when_no_pantry_items(self):
        ingredients = [_ing("kip", 500, "g", category="meat")]
        assert format_pantry_check(ingredients, lang="en") == ""


# --- format_full_ingredient_list ---

class TestFormatFullIngredientList:
    def test_merges_same_ingredient(self):
        r1 = _recipe(ingredients=[_ing("ui", 1, "stuks", "produce")])
        r2 = _recipe(ingredients=[_ing("ui", 2, "stuks", "produce")])
        result = format_full_ingredient_list([r1, r2], lang="en")
        assert "3stuks" in result or "3 stuks" in result

    def test_groups_by_category(self):
        r = _recipe(ingredients=[
            _ing("kip", 500, "g", "meat"),
            _ing("rijst", 300, "g", "pantry"),
        ])
        result = format_full_ingredient_list([r], lang="en")
        assert "[meat]" in result
        assert "[pantry]" in result
        # meat comes before pantry alphabetically
        assert result.index("[meat]") < result.index("[pantry]")

    def test_different_units_not_merged(self):
        r1 = _recipe(ingredients=[_ing("water", 200, "ml", "other")])
        r2 = _recipe(ingredients=[_ing("water", 1, "l", "other")])
        result = format_full_ingredient_list([r1, r2], lang="en")
        # Both should appear
        assert "water" in result


# --- format_cart_report ---

class TestFormatCartReport:
    def test_added_count(self):
        report = CartReport()
        report.added = [(_ing("kip"), {"product_id": "123"})]
        result = format_cart_report(report, lang="en")
        assert "1" in result
        assert "added" in result.lower()

    def test_not_found_listed(self):
        report = CartReport()
        report.not_found = [(_ing("truffel"), "No results")]
        result = format_cart_report(report, lang="en")
        assert "truffel" in result

    def test_errors_listed(self):
        report = CartReport()
        report.errors = [(_ing("kaas"), "API timeout")]
        result = format_cart_report(report, lang="en")
        assert "kaas" in result
        assert "API timeout" in result

    def test_footer_always_present(self):
        result = format_cart_report(CartReport(), lang="en")
        assert "Picnic" in result


# --- format_recipe_detail ---

class TestFormatRecipeDetail:
    def test_english_detail(self):
        recipe = _recipe(
            ingredients=[_ing("pasta", 500, "g"), _ing("sauce", 200, "ml")],
            instructions="1. Boil pasta\n2. Add sauce",
        )
        result = format_recipe_detail(recipe, lang="en")
        assert "**Test Recipe**" in result
        assert "Prep time:" in result
        assert "30 min" in result
        assert "Servings: 4" in result
        assert "pasta" in result
        assert "1. Boil pasta" in result

    def test_dutch_detail(self):
        recipe = _recipe()
        result = format_recipe_detail(recipe, lang="nl")
        assert "Bereidingstijd:" in result
        assert "Porties:" in result
