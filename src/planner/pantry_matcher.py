"""Claude-powered fuzzy matching of pantry items against ingredient lists."""

from __future__ import annotations

import logging

import anthropic

from ..conversation.prompts import MATCH_PANTRY_ITEMS
from ..models import Ingredient
from ..utils import parse_json_response

logger = logging.getLogger(__name__)


async def match_pantry_items(
    client: anthropic.Anthropic,
    model: str,
    message: str,
    ingredients: list[Ingredient],
) -> list[str]:
    """Match a parent's free-text pantry response against the ingredient list.

    Returns a list of ingredient names (as they appear in the ingredient list)
    that the parent indicated they already have.
    """
    ingredient_names = sorted({ing.name for ing in ingredients})
    ingredients_text = "\n".join(f"- {name}" for name in ingredient_names)

    prompt = MATCH_PANTRY_ITEMS.format(
        message=message,
        ingredients=ingredients_text,
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=300,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        result = parse_json_response(response.content[0].text)
        if isinstance(result, list):
            logger.info("Pantry match: %d items matched from message", len(result))
            return result
    except (anthropic.APIError, Exception) as e:
        logger.warning("Failed to match pantry items via Claude: %s", e)

    return []
