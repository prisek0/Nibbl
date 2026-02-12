"""Format meal plans and ingredient lists for iMessage readability."""

from __future__ import annotations

from ..models import CartReport, Ingredient, Recipe

DAYS = {
    "nl": {0: "Ma", 1: "Di", 2: "Wo", 3: "Do", 4: "Vr", 5: "Za", 6: "Zo"},
    "en": {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"},
}

_LABELS = {
    "menu_header": {"nl": "Hier is het menu voor deze week:", "en": "Here's the menu for this week:"},
    "pantry_question": {"nl": "Welke van deze dingen heb je al in huis?", "en": "Which of these do you already have at home?"},
    "pantry_footer": {"nl": "Stuur me wat je al hebt, dan sla ik die over.", "en": "Send me what you already have and I'll skip those."},
    "shopping_list": {"nl": "Boodschappenlijst:", "en": "Shopping list:"},
    "cart_added": {"nl": "{n} product(en) aan je Picnic mandje toegevoegd!", "en": "{n} product(s) added to your Picnic cart!"},
    "cart_not_found": {"nl": "Kon ik niet vinden:", "en": "Could not find:"},
    "cart_errors": {"nl": "Problemen bij toevoegen:", "en": "Problems adding:"},
    "cart_footer": {"nl": "Open de Picnic app om je mandje te controleren en te bestellen!", "en": "Open the Picnic app to review your cart and place your order!"},
    "prep_time": {"nl": "Bereidingstijd:", "en": "Prep time:"},
    "servings": {"nl": "Porties:", "en": "Servings:"},
    "ingredients": {"nl": "Ingredienten:", "en": "Ingredients:"},
    "instructions": {"nl": "Bereiding:", "en": "Instructions:"},
}


def _l(key: str, lang: str = "nl", **kwargs) -> str:
    text = _LABELS.get(key, {}).get(lang, _LABELS.get(key, {}).get("en", f"[{key}]"))
    return text.format(**kwargs) if kwargs else text


def format_meal_plan(recipes: list[Recipe], lang: str = "nl") -> str:
    """Format a meal plan for iMessage display."""
    days = DAYS.get(lang, DAYS["en"])
    lines = [_l("menu_header", lang) + "\n"]

    for recipe in recipes:
        day = days.get(recipe.planned_date.weekday(), "")
        day_num = recipe.planned_date.strftime("%d %b")
        time_info = ""
        if recipe.prep_time_minutes or recipe.cook_time_minutes:
            total = (recipe.prep_time_minutes or 0) + (recipe.cook_time_minutes or 0)
            time_info = f" ({total} min)"

        lines.append(f"{day} {day_num} — {recipe.name}{time_info}")
        lines.append(f"  {recipe.description}")
        lines.append("")

    return "\n".join(lines).strip()


def format_pantry_check(ingredients: list[Ingredient], lang: str = "nl") -> str:
    """Format a list of pantry staples to check with the parent."""
    pantry_categories = {"pantry", "spice"}
    pantry_items = [
        ing for ing in ingredients
        if ing.category in pantry_categories and not ing.optional
    ]

    if not pantry_items:
        return ""

    lines = [_l("pantry_question", lang) + "\n"]
    for ing in pantry_items:
        qty = f"{ing.quantity:.0f} {ing.unit}" if ing.quantity else ""
        lines.append(f"- {ing.name} {qty}".strip())

    lines.append("\n" + _l("pantry_footer", lang))
    return "\n".join(lines)


def format_full_ingredient_list(recipes: list[Recipe], lang: str = "nl") -> str:
    """Format the complete ingredient list across all recipes."""
    # Merge ingredients by normalized name
    merged: dict[str, Ingredient] = {}
    for recipe in recipes:
        for ing in recipe.ingredients:
            key = ing.name.lower().strip()
            if key in merged and merged[key].unit == ing.unit:
                merged[key] = Ingredient(
                    name=ing.name,
                    quantity=merged[key].quantity + ing.quantity,
                    unit=ing.unit,
                    category=ing.category,
                    optional=ing.optional and merged[key].optional,
                )
            else:
                merged.setdefault(key, ing)

    # Group by category
    by_category: dict[str, list[Ingredient]] = {}
    for ing in merged.values():
        by_category.setdefault(ing.category, []).append(ing)

    lines = [_l("shopping_list", lang) + "\n"]
    for category, items in sorted(by_category.items()):
        lines.append(f"[{category}]")
        for ing in sorted(items, key=lambda i: i.name):
            qty = f"{ing.quantity:.0f}{ing.unit}" if ing.quantity else ""
            lines.append(f"  {ing.name} {qty}".strip())
        lines.append("")

    return "\n".join(lines).strip()


def format_cart_report(report: CartReport, lang: str = "nl") -> str:
    """Format the cart filling report for iMessage."""
    lines = []

    if report.added:
        lines.append(_l("cart_added", lang, n=len(report.added)))

    if report.not_found:
        lines.append("")
        lines.append(_l("cart_not_found", lang))
        for ing, note in report.not_found:
            lines.append(f"- {ing.name} ({note})")

    if report.errors:
        lines.append("")
        lines.append(_l("cart_errors", lang))
        for ing, err in report.errors:
            lines.append(f"- {ing.name}: {err}")

    lines.append("")
    lines.append(_l("cart_footer", lang))

    return "\n".join(lines)


def format_recipe_detail(recipe: Recipe, lang: str = "nl") -> str:
    """Format a single recipe with full details (for when a family member asks)."""
    total_time = (recipe.prep_time_minutes or 0) + (recipe.cook_time_minutes or 0)
    lines = [
        f"**{recipe.name}**",
        recipe.description,
        "",
        f"{_l('prep_time', lang)} {total_time} min",
        f"{_l('servings', lang)} {recipe.servings}",
        "",
        _l("ingredients", lang),
    ]

    for ing in recipe.ingredients:
        qty = f"{ing.quantity:.0f} {ing.unit}" if ing.quantity else ""
        lines.append(f"- {qty} {ing.name}".strip())

    lines.append("")
    lines.append(_l("instructions", lang))
    lines.append(recipe.instructions)

    return "\n".join(lines)
