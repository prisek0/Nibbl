"""Search for ingredients on Picnic and add them to the shopping cart."""

from __future__ import annotations

import json
import logging

import anthropic

from ..conversation.prompts import GENERATE_SEARCH_TERMS, SELECT_BEST_PRODUCT
from ..models import CartReport, Ingredient
from ..utils import parse_json_response
from .client import PicnicClient, PicnicAPIError

logger = logging.getLogger(__name__)


class CartFiller:
    """Matches recipe ingredients to Picnic products and fills the cart."""

    def __init__(
        self,
        picnic: PicnicClient,
        claude: anthropic.Anthropic,
        model: str,
    ):
        self.picnic = picnic
        self.claude = claude
        self.model = model
        # Cache successful matches to avoid repeated searches
        self._match_cache: dict[str, dict] = {}

    async def fill_cart(self, ingredients: list[Ingredient]) -> CartReport:
        """Search and add all needed ingredients to the Picnic cart.

        Skips ingredients marked as already_available.
        Returns a report of what was added, not found, or errored.
        """
        report = CartReport()
        merged = self._merge_ingredients(ingredients)

        for ingredient in merged:
            if ingredient.already_available:
                report.skipped.append(ingredient)
                continue

            try:
                match = await self._search_and_match(ingredient)

                if match and match.get("product_id") and match.get("confidence", 0) > 0.5:
                    self.picnic.add_product(
                        match["product_id"],
                        match.get("count", 1),
                    )
                    ingredient.picnic_product_id = match["product_id"]
                    ingredient.picnic_product_name = match.get("product_name", "")
                    ingredient.picnic_added_to_cart = True
                    ingredient.search_status = "found"
                    report.added.append((ingredient, match))
                else:
                    ingredient.search_status = "not_found"
                    note = match.get("note", "No match found") if match else "No results"
                    report.not_found.append((ingredient, note))

            except PicnicAPIError as e:
                ingredient.search_status = "not_found"
                report.errors.append((ingredient, str(e)))
            except Exception as e:
                logger.error("Error matching %s: %s", ingredient.name, e, exc_info=True)
                report.errors.append((ingredient, str(e)))

        logger.info(
            "Cart fill complete: %d added, %d not found, %d skipped, %d errors",
            len(report.added),
            len(report.not_found),
            len(report.skipped),
            len(report.errors),
        )
        return report

    async def _search_and_match(self, ingredient: Ingredient) -> dict | None:
        """Search Picnic and pick the best product match for an ingredient."""
        cache_key = ingredient.name.lower().strip()
        if cache_key in self._match_cache:
            logger.debug("Cache hit for '%s'", ingredient.name)
            return self._match_cache[cache_key]

        # Generate Dutch search terms via Claude
        search_terms = await self._generate_search_terms(ingredient)

        all_results: list[dict] = []
        seen_ids: set[str] = set()
        for term in search_terms:
            try:
                results = self.picnic.search(term)
                for r in results:
                    pid = r.get("id", "")
                    if pid not in seen_ids:
                        seen_ids.add(pid)
                        all_results.append(r)
                if all_results:
                    break  # got results, skip remaining terms
            except PicnicAPIError:
                logger.warning("Picnic search failed for term '%s'", term)
                continue

        if not all_results:
            return None

        # Use Claude to select the best match
        match = await self._select_best_match(ingredient, all_results[:15])

        if match and match.get("product_id"):
            self._match_cache[cache_key] = match

        return match

    async def _generate_search_terms(self, ingredient: Ingredient) -> list[str]:
        """Generate Dutch supermarket search terms for an ingredient."""
        prompt = GENERATE_SEARCH_TERMS.format(
            ingredient_name=ingredient.name,
            quantity=ingredient.quantity,
            unit=ingredient.unit,
            category=ingredient.category,
        )

        try:
            response = self.claude.messages.create(
                model=self.model,
                max_tokens=200,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            terms = parse_json_response(response.content[0].text)
            if isinstance(terms, list):
                return terms[:3]
        except (json.JSONDecodeError, anthropic.APIError) as e:
            logger.warning("Failed to generate search terms for '%s': %s", ingredient.name, e)

        # Fallback: use the ingredient name directly
        return [ingredient.name]

    async def _select_best_match(
        self, ingredient: Ingredient, products: list[dict]
    ) -> dict | None:
        """Use Claude to select the best product match from search results."""
        products_list = "\n".join(
            f"- ID: {p.get('id', '?')}, "
            f"Name: {p.get('name', '?')}, "
            f"Quantity: {p.get('unit_quantity', p.get('unit_quantity_sub', '?'))}, "
            f"Price: EUR {p.get('display_price', 0) / 100:.2f}"
            for p in products
        )

        prompt = SELECT_BEST_PRODUCT.format(
            quantity=ingredient.quantity,
            unit=ingredient.unit,
            ingredient_name=ingredient.name,
            products_list=products_list,
        )

        try:
            response = self.claude.messages.create(
                model=self.model,
                max_tokens=300,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            return parse_json_response(response.content[0].text)
        except (json.JSONDecodeError, anthropic.APIError) as e:
            logger.warning("Failed to select product for '%s': %s", ingredient.name, e)
            return None

    def _merge_ingredients(self, ingredients: list[Ingredient]) -> list[Ingredient]:
        """Merge same ingredients across recipes, summing quantities."""
        merged: dict[str, Ingredient] = {}

        for ing in ingredients:
            key = ing.name.lower().strip()
            if key in merged and merged[key].unit == ing.unit:
                merged[key] = Ingredient(
                    name=ing.name,
                    quantity=merged[key].quantity + ing.quantity,
                    unit=ing.unit,
                    category=ing.category,
                    optional=ing.optional and merged[key].optional,
                    already_available=ing.already_available and merged[key].already_available,
                )
            else:
                merged.setdefault(key, Ingredient(
                    name=ing.name,
                    quantity=ing.quantity,
                    unit=ing.unit,
                    category=ing.category,
                    optional=ing.optional,
                    already_available=ing.already_available,
                ))

        return list(merged.values())
