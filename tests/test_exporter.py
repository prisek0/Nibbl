"""Tests for src/exporter.py — markdown export helpers and rendering."""

from datetime import date

from src.exporter import (
    _dedup_ingredients,
    _escape_yaml,
    _format_qty,
    _sanitize_filename,
    MarkdownExporter,
)
from src.models import Ingredient, MealPlanSession, Recipe, SessionState


# --- _sanitize_filename ---

class TestSanitizeFilename:
    def test_basic_name(self):
        assert _sanitize_filename("Spaghetti Bolognese") == "Spaghetti Bolognese"

    def test_special_characters_replaced(self):
        # Special chars are replaced by "-", then collapsed with whitespace
        assert _sanitize_filename('Pasta: A <Story> of "Love"') == "Pasta A Story of Love"

    def test_collapses_whitespace_and_dashes(self):
        assert _sanitize_filename("Pasta   Risotto   Best") == "Pasta Risotto Best"

    def test_strips_trailing_dots(self):
        assert _sanitize_filename("recipe...") == "recipe"

    def test_truncates_long_names(self):
        long_name = "A" * 250
        assert len(_sanitize_filename(long_name)) == 200

    def test_empty_string(self):
        assert _sanitize_filename("") == ""

    def test_pipe_and_backslash(self):
        result = _sanitize_filename("Pad Thai | Best\\Ever")
        assert "\\" not in result
        assert "|" not in result


# --- _format_qty ---

class TestFormatQty:
    def test_grams_attached(self):
        assert _format_qty(500, "g") == "500g"

    def test_milliliters_attached(self):
        assert _format_qty(200, "ml") == "200ml"

    def test_kg_attached(self):
        assert _format_qty(1.5, "kg") == "1.5kg"

    def test_spaced_unit(self):
        assert _format_qty(2, "el") == "2 el"

    def test_stuks_spaced(self):
        assert _format_qty(3, "stuks") == "3 stuks"

    def test_zero_quantity_returns_unit(self):
        assert _format_qty(0, "snuf") == "snuf"

    def test_no_unit_returns_number(self):
        assert _format_qty(4, "") == "4"

    def test_zero_quantity_no_unit(self):
        assert _format_qty(0, "") == ""

    def test_integer_display(self):
        # 500.0 should display as "500", not "500.0"
        assert _format_qty(500.0, "g") == "500g"

    def test_fractional_display(self):
        assert _format_qty(1.5, "l") == "1.5l"


# --- _dedup_ingredients ---

class TestDedupIngredients:
    def _ing(self, name, qty, unit="g", category="other"):
        return Ingredient(name=name, quantity=qty, unit=unit, category=category)

    def test_merges_same_name_and_unit(self):
        result = _dedup_ingredients([
            self._ing("olijfolie", 2, "el"),
            self._ing("olijfolie", 1, "el"),
        ])
        assert len(result) == 1
        assert result[0].quantity == 3

    def test_preserves_order(self):
        result = _dedup_ingredients([
            self._ing("knoflook", 2, "tenen"),
            self._ing("ui", 1, "stuks"),
            self._ing("knoflook", 1, "tenen"),
        ])
        assert [r.name for r in result] == ["knoflook", "ui"]
        assert result[0].quantity == 3

    def test_different_units_kept_separate(self):
        result = _dedup_ingredients([
            self._ing("water", 200, "ml"),
            self._ing("water", 1, "l"),
        ])
        assert len(result) == 2

    def test_case_insensitive_matching(self):
        result = _dedup_ingredients([
            self._ing("Olijfolie", 2, "el"),
            self._ing("olijfolie", 1, "el"),
        ])
        assert len(result) == 1
        assert result[0].quantity == 3

    def test_empty_list(self):
        assert _dedup_ingredients([]) == []

    def test_single_item(self):
        result = _dedup_ingredients([self._ing("zout", 1, "tl")])
        assert len(result) == 1


# --- _escape_yaml ---

class TestEscapeYaml:
    def test_plain_string(self):
        assert _escape_yaml("Italian") == "Italian"

    def test_quotes_escaped(self):
        assert _escape_yaml('Chef\'s "Special"') == 'Chef\'s \\"Special\\"'

    def test_backslash_escaped(self):
        assert _escape_yaml("path\\to") == "path\\\\to"


# --- _render_recipe / _render_meal_plan ---

def _make_recipe(**kwargs):
    defaults = dict(
        id="r1",
        name="Spaghetti Bolognese",
        description="Classic Italian pasta",
        planned_date=date(2026, 2, 13),
        servings=4,
        prep_time_minutes=15,
        cook_time_minutes=25,
        cuisine="Italian",
        tags=["Italian", "quick"],
        ingredients=[
            Ingredient(name="spaghetti", quantity=500, unit="g", category="pantry"),
            Ingredient(name="gehakt", quantity=400, unit="g", category="meat"),
        ],
        instructions="1. Cook pasta\n2. Brown meat\n3. Combine",
    )
    defaults.update(kwargs)
    return Recipe(**defaults)


def _make_session(**kwargs):
    defaults = dict(
        id="s1",
        state=SessionState.COMPLETED,
        plan_start_date=date(2026, 2, 13),
        plan_end_date=date(2026, 2, 16),
    )
    defaults.update(kwargs)
    return MealPlanSession(**defaults)


class TestRenderRecipe:
    def setup_method(self):
        from src.config import ExportConfig
        self.exporter = MarkdownExporter(ExportConfig(path="/tmp/test"), lang="en")

    def test_frontmatter_present(self):
        md = self.exporter._render_recipe(_make_recipe())
        assert md.startswith("---\n")
        assert 'cuisine: "Italian"' in md
        assert "total_time: 40" in md
        assert "date_planned: 2026-02-13" in md

    def test_ingredient_bullets(self):
        md = self.exporter._render_recipe(_make_recipe())
        assert "- 500g spaghetti" in md
        assert "- 400g gehakt" in md

    def test_instructions_present(self):
        md = self.exporter._render_recipe(_make_recipe())
        assert "## Instructions" in md
        assert "1. Cook pasta" in md

    def test_tags_include_cuisine(self):
        md = self.exporter._render_recipe(_make_recipe())
        assert "  - Italian" in md
        assert "  - quick" in md

    def test_deduplicates_ingredients(self):
        recipe = _make_recipe(ingredients=[
            Ingredient(name="olijfolie", quantity=2, unit="el", category="pantry"),
            Ingredient(name="olijfolie", quantity=1, unit="el", category="pantry"),
        ])
        md = self.exporter._render_recipe(recipe)
        assert "3 el olijfolie" in md
        assert md.count("olijfolie") == 1


class TestRenderMealPlan:
    def setup_method(self):
        from src.config import ExportConfig
        self.exporter = MarkdownExporter(ExportConfig(path="/tmp/test"), lang="en")

    def test_wikilinks(self):
        recipes = [
            _make_recipe(name="Pasta", planned_date=date(2026, 2, 13)),
            _make_recipe(name="Curry", planned_date=date(2026, 2, 14)),
        ]
        session = _make_session()
        md = self.exporter._render_meal_plan(recipes, session)
        assert "[[Pasta]]" in md
        assert "[[Curry]]" in md

    def test_table_header(self):
        recipes = [_make_recipe()]
        session = _make_session()
        md = self.exporter._render_meal_plan(recipes, session)
        assert "| Day | Date | Meal | Time |" in md

    def test_frontmatter_dates(self):
        recipes = [_make_recipe()]
        session = _make_session()
        md = self.exporter._render_meal_plan(recipes, session)
        assert "date_start: 2026-02-13" in md
        assert "date_end: 2026-02-16" in md

    def test_dutch_day_names(self):
        exporter_nl = MarkdownExporter(
            __import__("src.config", fromlist=["ExportConfig"]).ExportConfig(path="/tmp/test"),
            lang="nl",
        )
        recipes = [_make_recipe(planned_date=date(2026, 2, 13))]  # Friday
        session = _make_session()
        md = exporter_nl._render_meal_plan(recipes, session)
        assert "Vr" in md
