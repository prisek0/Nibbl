"""Shared utilities for FoodAgend."""

from __future__ import annotations

import json
import re


def parse_json_response(text: str) -> dict | list:
    """Parse JSON from a Claude response, stripping markdown code fences if present."""
    cleaned = text.strip()

    # Strip markdown code fences: ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1).strip()

    return json.loads(cleaned)
