"""Extract and manage food preferences using Claude API."""

from __future__ import annotations

import json
import logging

import anthropic

from ..conversation.prompts import PREFERENCE_EXTRACTION
from ..database import Database
from ..models import FamilyMember, Preference
from ..utils import parse_json_response

logger = logging.getLogger(__name__)


class PreferenceEngine:
    """Extracts preferences from messages and manages the preference store."""

    def __init__(self, client: anthropic.Anthropic, model: str, db: Database):
        self.client = client
        self.model = model
        self.db = db

    async def extract_and_store(
        self, member: FamilyMember, message_text: str
    ) -> tuple[list[Preference], list[str]]:
        """Extract preferences from a message and store new ones.

        Returns:
            Tuple of (new/updated preferences, specific wishes for this week).
        """
        existing = self.db.get_preferences_for_member(member.id)
        existing_text = self._format_existing(existing) if existing else "None yet."

        prompt = PREFERENCE_EXTRACTION.format(
            member_name=member.name,
            member_role=member.role.value,
            message_text=message_text,
            existing_preferences=existing_text,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            data = parse_json_response(response.content[0].text)
        except (json.JSONDecodeError, ValueError, anthropic.APIError) as e:
            logger.error("Failed to extract preferences: %s", e)
            return [], []

        if not data.get("has_food_content", True):
            return [], []

        new_prefs: list[Preference] = []
        for p in data.get("preferences", []):
            # Always check for existing match to avoid duplicates
            match = self._find_matching(existing, p["detail"], p["category"])
            if match and match.id is not None:
                new_conf = min(1.0, max(match.confidence, p.get("confidence", 0.5)) + 0.1)
                self.db.update_preference_confidence(match.id, new_conf)
                continue

            pref = Preference(
                member_id=member.id,
                category=p["category"],
                detail=p["detail"],
                confidence=p.get("confidence", 0.5),
                source="conversation",
                extracted_from=message_text[:200],
            )
            pref.id = self.db.add_preference(pref)
            new_prefs.append(pref)
            existing.append(pref)  # prevent duplicates within same extraction

        wishes = data.get("specific_wishes", [])
        if wishes:
            logger.info(
                "Extracted %d preference(s) and %d wish(es) from %s",
                len(new_prefs), len(wishes), member.name,
            )

        return new_prefs, wishes

    def get_formatted_preferences(self, member_id: str) -> str:
        """Get a formatted summary of a member's preferences for prompts."""
        prefs = self.db.get_preferences_for_member(member_id)
        if not prefs:
            return "No known preferences."
        return self._format_existing(prefs)

    def get_all_formatted(self, members: list[FamilyMember]) -> str:
        """Get formatted preferences for all family members."""
        sections = []
        for m in members:
            prefs = self.get_formatted_preferences(m.id)
            sections.append(f"### {m.name} ({m.role.value})\n{prefs}")
        return "\n\n".join(sections)

    def _format_existing(self, prefs: list[Preference]) -> str:
        lines = []
        for p in prefs:
            conf = f"[{p.confidence:.0%}]" if p.confidence < 1.0 else ""
            lines.append(f"- {p.category}: {p.detail} {conf}".strip())
        return "\n".join(lines)

    def _find_matching(
        self, existing: list[Preference], detail: str, category: str
    ) -> Preference | None:
        """Find an existing preference that matches the new one."""
        detail_lower = detail.lower()
        for p in existing:
            if p.category == category and (
                detail_lower in p.detail.lower() or p.detail.lower() in detail_lower
            ):
                return p
        return None
