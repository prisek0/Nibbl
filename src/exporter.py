"""Export recipes and meal plans as Obsidian-compatible markdown files."""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from .config import ExportConfig
from .models import Ingredient, MealPlanSession, Recipe

logger = logging.getLogger(__name__)

DAYS = {
    "nl": {0: "Ma", 1: "Di", 2: "Wo", 3: "Do", 4: "Vr", 5: "Za", 6: "Zo"},
    "en": {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"},
}

INDEX_CONTENT = """\
# Nibbl

## Recent Meal Plans

```dataview
TABLE date_start AS "Start", date_end AS "End"
FROM "meal-plans"
SORT date_start DESC
LIMIT 10
```

## All Recipes

```dataview
TABLE cuisine, total_time AS "Time (min)", servings
FROM "recipes"
SORT file.name ASC
```

## Quick Meals (< 30 min)

```dataview
TABLE cuisine, total_time AS "Time (min)"
FROM "recipes"
WHERE total_time < 30
SORT file.name ASC
```

## By Cuisine

```dataview
TABLE length(rows) AS "Count"
FROM "recipes"
GROUP BY cuisine
SORT rows.cuisine ASC
```
"""


def _sanitize_filename(name: str) -> str:
    """Sanitize a recipe name for use as a filename."""
    cleaned = re.sub(r'[\\/:*?"<>|]', "-", name)
    cleaned = re.sub(r"[-\s]+", " ", cleaned).strip().strip(".")
    return cleaned[:200]


def _format_qty(quantity: float, unit: str) -> str:
    """Format a quantity+unit for an ingredient bullet, e.g. '500g' or '2 el'."""
    if not quantity:
        return unit or ""
    q = str(int(quantity)) if quantity == int(quantity) else f"{quantity:.1f}"
    if not unit:
        return q
    # Units that attach directly to the number (g, ml, kg, l)
    if unit in ("g", "ml", "kg", "l", "cl", "dl"):
        return f"{q}{unit}"
    return f"{q} {unit}"


def _dedup_ingredients(ingredients: list[Ingredient]) -> list[Ingredient]:
    """Deduplicate ingredients, summing quantities. Preserves original order."""
    seen: dict[str, int] = {}  # name_lower -> index in result
    result: list[Ingredient] = []
    for ing in ingredients:
        key = ing.name.lower().strip()
        if key in seen and result[seen[key]].unit == ing.unit:
            existing = result[seen[key]]
            result[seen[key]] = Ingredient(
                name=existing.name,
                quantity=existing.quantity + ing.quantity,
                unit=existing.unit,
                category=existing.category,
            )
        else:
            seen[key] = len(result)
            result.append(Ingredient(
                name=ing.name,
                quantity=ing.quantity,
                unit=ing.unit,
                category=ing.category,
            ))
    return result


def _escape_yaml(value: str) -> str:
    """Escape a string for YAML double-quoted value."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


class MarkdownExporter:
    """Exports recipes and meal plans as Obsidian-compatible markdown files."""

    def __init__(self, config: ExportConfig, lang: str = "en"):
        self.root = Path(config.path).expanduser()
        self.recipe_dir = self.root / "recipes"
        self.plan_dir = self.root / "meal-plans"
        self.lang = lang

    def _ensure_dirs(self) -> None:
        self.recipe_dir.mkdir(parents=True, exist_ok=True)
        self.plan_dir.mkdir(parents=True, exist_ok=True)

    def export_session(
        self, recipes: list[Recipe], session: MealPlanSession
    ) -> None:
        """Export all recipes and the meal plan for a session."""
        self._ensure_dirs()

        for recipe in recipes:
            self._export_recipe(recipe)

        self._export_meal_plan(recipes, session)
        self._ensure_index()

        logger.info(
            "Exported %d recipe(s) and meal plan to %s",
            len(recipes), self.root,
        )

    def _export_recipe(self, recipe: Recipe) -> None:
        """Export a single recipe as markdown. Skips if file already exists."""
        filename = _sanitize_filename(recipe.name) + ".md"
        filepath = self.recipe_dir / filename

        if filepath.exists():
            logger.debug("Recipe already exists, skipping: %s", recipe.name)
            return

        content = self._render_recipe(recipe)
        filepath.write_text(content, encoding="utf-8")
        logger.info("Exported recipe: %s", filepath.name)

    def _export_meal_plan(
        self, recipes: list[Recipe], session: MealPlanSession
    ) -> None:
        """Export the meal plan as markdown with Obsidian wikilinks."""
        if not recipes:
            return

        start = session.plan_start_date or recipes[0].planned_date
        filename = f"{start.isoformat()} - Meal Plan.md"
        filepath = self.plan_dir / filename

        content = self._render_meal_plan(recipes, session)
        filepath.write_text(content, encoding="utf-8")
        logger.info("Exported meal plan: %s", filepath.name)

    def _ensure_index(self) -> None:
        """Create index.md with Dataview queries if it doesn't exist yet."""
        filepath = self.root / "index.md"
        if filepath.exists():
            return
        filepath.write_text(INDEX_CONTENT, encoding="utf-8")
        logger.info("Created vault index: %s", filepath)

    def _render_recipe(self, recipe: Recipe) -> str:
        total_time = (recipe.prep_time_minutes or 0) + (recipe.cook_time_minutes or 0)

        # Build tags: include cuisine + recipe tags, deduplicated
        tags = []
        if recipe.cuisine:
            tags.append(recipe.cuisine)
        for tag in recipe.tags:
            if tag not in tags:
                tags.append(tag)
        tags_yaml = "\n".join(f"  - {tag}" for tag in tags) if tags else "  []"

        lines = [
            "---",
            f'cuisine: "{_escape_yaml(recipe.cuisine)}"',
            "tags:",
            tags_yaml,
            f"servings: {recipe.servings}",
            f"prep_time: {recipe.prep_time_minutes or 0}",
            f"cook_time: {recipe.cook_time_minutes or 0}",
            f"total_time: {total_time}",
            f"date_planned: {recipe.planned_date.isoformat()}",
            f"date_created: {date.today().isoformat()}",
            "---",
            "",
            f"# {recipe.name}",
            "",
            recipe.description,
            "",
            "## Ingredients",
            "",
        ]

        deduped = _dedup_ingredients(recipe.ingredients)
        for ing in deduped:
            qty_str = _format_qty(ing.quantity, ing.unit)
            if qty_str:
                lines.append(f"- {qty_str} {ing.name}")
            else:
                lines.append(f"- {ing.name}")

        lines.extend([
            "",
            "## Instructions",
            "",
            recipe.instructions,
        ])

        return "\n".join(lines) + "\n"

    def _render_meal_plan(
        self, recipes: list[Recipe], session: MealPlanSession
    ) -> str:
        days = DAYS.get(self.lang, DAYS["en"])
        start = session.plan_start_date or recipes[0].planned_date
        end = session.plan_end_date or recipes[-1].planned_date

        lines = [
            "---",
            f"date_start: {start.isoformat()}",
            f"date_end: {end.isoformat()}",
            f"date_created: {date.today().isoformat()}",
            "---",
            "",
            f"# Meal Plan: {start.strftime('%b %d')} \u2013 {end.strftime('%b %d, %Y')}",
            "",
            "| Day | Date | Meal | Time |",
            "|-----|------|------|------|",
        ]

        for recipe in recipes:
            day_name = days.get(recipe.planned_date.weekday(), "")
            date_str = recipe.planned_date.strftime("%b %d")
            total = (recipe.prep_time_minutes or 0) + (recipe.cook_time_minutes or 0)
            lines.append(f"| {day_name} | {date_str} | [[{recipe.name}]] | {total} min |")

        lines.extend(["", "## Details", ""])

        for recipe in recipes:
            day_name = days.get(recipe.planned_date.weekday(), "")
            date_str = recipe.planned_date.strftime("%b %d")
            lines.extend([
                f"### {day_name} {date_str} \u2014 [[{recipe.name}]]",
                recipe.description,
                "",
            ])

        return "\n".join(lines)
