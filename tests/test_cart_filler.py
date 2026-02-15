"""Tests for src/picnic/cart_filler.py — ingredient merging logic."""

from src.models import Ingredient
from src.picnic.cart_filler import CartFiller


def _merge_ingredients(ingredients):
    return CartFiller._merge_ingredients(None, ingredients)


def _ing(name, qty, unit="g", category="other", optional=False, already_available=False):
    return Ingredient(
        name=name,
        quantity=qty,
        unit=unit,
        category=category,
        optional=optional,
        already_available=already_available,
    )


class TestMergeIngredients:
    def test_sums_same_name_and_unit(self):
        result = _merge_ingredients([
            _ing("ui", 1, "stuks"),
            _ing("ui", 2, "stuks"),
        ])
        assert len(result) == 1
        assert result[0].quantity == 3

    def test_different_units_first_wins(self):
        """When same name has different units, first unit wins (setdefault)."""
        result = _merge_ingredients([
            _ing("water", 200, "ml"),
            _ing("water", 1, "l"),
        ])
        assert len(result) == 1
        assert result[0].unit == "ml"
        assert result[0].quantity == 200

    def test_case_insensitive(self):
        result = _merge_ingredients([
            _ing("Olijfolie", 2, "el"),
            _ing("olijfolie", 1, "el"),
        ])
        assert len(result) == 1
        assert result[0].quantity == 3

    def test_optional_flag_and_logic(self):
        """Merged ingredient is optional only if ALL sources are optional."""
        result = _merge_ingredients([
            _ing("zout", 1, "tl", optional=True),
            _ing("zout", 1, "tl", optional=False),
        ])
        assert len(result) == 1
        assert result[0].optional is False

    def test_already_available_and_logic(self):
        """Merged ingredient is available only if ALL sources are available."""
        result = _merge_ingredients([
            _ing("rijst", 200, "g", already_available=True),
            _ing("rijst", 100, "g", already_available=False),
        ])
        assert len(result) == 1
        assert result[0].already_available is False

    def test_both_available(self):
        result = _merge_ingredients([
            _ing("olie", 1, "el", already_available=True),
            _ing("olie", 1, "el", already_available=True),
        ])
        assert result[0].already_available is True

    def test_empty_list(self):
        assert _merge_ingredients([]) == []

    def test_single_item(self):
        result = _merge_ingredients([_ing("kip", 500, "g")])
        assert len(result) == 1
        assert result[0].name == "kip"
        assert result[0].quantity == 500

    def test_preserves_category(self):
        result = _merge_ingredients([
            _ing("kip", 300, "g", category="meat"),
            _ing("kip", 200, "g", category="meat"),
        ])
        assert result[0].category == "meat"
