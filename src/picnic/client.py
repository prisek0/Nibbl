"""Picnic API client wrapper using python-picnic-api2."""

from __future__ import annotations

import logging

from python_picnic_api2 import PicnicAPI
from python_picnic_api2.session import PicnicAuthError

logger = logging.getLogger(__name__)


class PicnicAPIError(Exception):
    """Raised when a Picnic API call fails."""


class PicnicClient:
    """Thin wrapper around python-picnic-api2.

    Keeps our interface stable so cart_filler and main.py don't need
    to know about the underlying library.
    """

    def __init__(
        self,
        username: str,
        password: str,
        country_code: str = "NL",
    ):
        self.username = username
        self.password = password
        self.country_code = country_code
        self._api: PicnicAPI | None = None

    def login(self) -> None:
        """Authenticate with Picnic."""
        try:
            self._api = PicnicAPI(
                username=self.username,
                password=self.password,
                country_code=self.country_code,
            )
            logger.info("Successfully logged in to Picnic")
        except (PicnicAuthError, Exception) as e:
            raise PicnicAPIError(f"Login failed: {e}") from e

    def _ensure_api(self) -> PicnicAPI:
        if not self._api:
            raise PicnicAPIError("Not authenticated. Call login() first.")
        return self._api

    def search(self, query: str) -> list[dict]:
        """Search for products.

        Returns a flat list of product dicts with id, name, display_price, etc.
        """
        api = self._ensure_api()
        try:
            raw = api.search(query)
            # Library returns [{"items": [...]}] — flatten to just the items
            items = []
            for group in raw:
                if isinstance(group, dict):
                    items.extend(group.get("items", []))
            logger.debug("Search '%s' returned %d results", query, len(items))
            return items
        except PicnicAuthError as e:
            raise PicnicAPIError(f"Search failed (auth): {e}") from e

    def get_cart(self) -> dict:
        """Get the current shopping cart."""
        api = self._ensure_api()
        try:
            return api.get_cart()
        except PicnicAuthError as e:
            raise PicnicAPIError(f"Get cart failed: {e}") from e

    def add_product(self, product_id: str, count: int = 1) -> dict:
        """Add a product to the shopping cart."""
        api = self._ensure_api()
        try:
            result = api.add_product(product_id, count)
            logger.info("Added %dx %s to cart", count, product_id)
            return result
        except PicnicAuthError as e:
            raise PicnicAPIError(f"Add product failed: {e}") from e

    def remove_product(self, product_id: str, count: int = 1) -> dict:
        """Remove a product from the shopping cart."""
        api = self._ensure_api()
        try:
            return api.remove_product(product_id, count)
        except PicnicAuthError as e:
            raise PicnicAPIError(f"Remove product failed: {e}") from e

    def clear_cart(self) -> dict:
        """Clear all items from the shopping cart."""
        api = self._ensure_api()
        try:
            return api.clear_cart()
        except PicnicAuthError as e:
            raise PicnicAPIError(f"Clear cart failed: {e}") from e

    def get_delivery_slots(self) -> dict:
        """Get available delivery slots."""
        api = self._ensure_api()
        try:
            return api.get_delivery_slots()
        except PicnicAuthError as e:
            raise PicnicAPIError(f"Get delivery slots failed: {e}") from e

    def close(self) -> None:
        """Close the HTTP session."""
        if self._api:
            self._api.session.close()
