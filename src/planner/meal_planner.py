"""Meal plan generation and conversation using Claude API."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, timedelta

import anthropic

from ..utils import parse_json_response
from ..conversation.prompts import (
    CLASSIFY_MESSAGE,
    MEAL_PLAN_GENERATION,
    MEAL_PLAN_REVISION,
    SYSTEM_CONVERSATION,
)
from ..database import Database
from ..models import (
    ConversationEntry,
    FamilyMember,
    Ingredient,
    MealPlan,
    Recipe,
)

logger = logging.getLogger(__name__)

MONTHS_NL = {
    1: "januari", 2: "februari", 3: "maart", 4: "april",
    5: "mei", 6: "juni", 7: "juli", 8: "augustus",
    9: "september", 10: "oktober", 11: "november", 12: "december",
}

SEASONS = {
    (12, 1, 2): "winter",
    (3, 4, 5): "lente",
    (6, 7, 8): "zomer",
    (9, 10, 11): "herfst",
}


def _get_season(month: int) -> str:
    for months, season in SEASONS.items():
        if month in months:
            return season
    return "onbekend"


class MealPlanner:
    """Generates meal plans and handles conversation via Claude API."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        model_planning: str,
        model_conversation: str,
        model_extraction: str,
        db: Database,
    ):
        self.client = client
        self.model_planning = model_planning
        self.model_conversation = model_conversation
        self.model_extraction = model_extraction
        self.db = db

    async def generate_meal_plan(
        self,
        members: list[FamilyMember],
        all_preferences: str,
        specific_wishes: dict[str, list[str]],
        num_days: int = 4,
        lang: str = "nl",
    ) -> MealPlan:
        """Generate a meal plan using Claude."""
        today = date.today()
        # Start from tomorrow
        start = today + timedelta(days=1)

        # Format inputs
        family_profiles = "\n".join(
            f"- {m.name} ({m.role.value})" for m in members
        )
        wishes_text = self._format_wishes(specific_wishes, members)
        history = self.db.get_recent_meal_history(weeks=3)
        history_text = (
            "\n".join(f"- {h.recipe_name} ({h.cuisine}, {h.cooked_date})" for h in history)
            if history
            else "No recent history."
        )

        month = MONTHS_NL.get(today.month, str(today.month))
        season = _get_season(today.month)

        language = "Dutch" if lang == "nl" else "English"
        prompt = MEAL_PLAN_GENERATION.format(
            num_days=num_days,
            start_date=start.isoformat(),
            family_profiles=family_profiles,
            specific_wishes=wishes_text or "No specific requests.",
            all_preferences=all_preferences,
            recent_history=history_text,
            month=month,
            season=season,
            family_size=len(members),
            language=language,
        )

        response = self.client.messages.create(
            model=self.model_planning,
            max_tokens=4096,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}],
        )

        data = parse_json_response(response.content[0].text)
        return self._parse_meal_plan(data)

    async def revise_meal_plan(
        self,
        current_recipes: list[Recipe],
        feedback: str,
    ) -> MealPlan:
        """Revise an existing meal plan based on parent feedback."""
        current_plan_text = self._format_plan_for_revision(current_recipes)

        prompt = MEAL_PLAN_REVISION.format(
            current_plan=current_plan_text,
            feedback=feedback,
        )

        response = self.client.messages.create(
            model=self.model_planning,
            max_tokens=4096,
            temperature=0.7,
            messages=[{"role": "user", "content": prompt}],
        )

        data = parse_json_response(response.content[0].text)
        return self._parse_meal_plan(data)

    async def classify_message(
        self,
        message_text: str,
        current_state: str,
        sender_role: str,
    ) -> dict:
        """Classify an incoming message's intent."""
        prompt = CLASSIFY_MESSAGE.format(
            message_text=message_text,
            current_state=current_state,
            sender_role=sender_role,
        )

        response = self.client.messages.create(
            model=self.model_extraction,
            max_tokens=200,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )

        try:
            return parse_json_response(response.content[0].text)
        except json.JSONDecodeError:
            return {"intent": "other", "confidence": 0.0, "summary": "Could not classify"}

    async def generate_reply(
        self,
        conversation_history: list[ConversationEntry],
        system_context: str,
        member: FamilyMember,
        lang: str = "nl",
    ) -> str:
        """Generate a conversational reply for iMessage."""
        lang_name = "Dutch" if lang == "nl" else "English"
        system_prompt = SYSTEM_CONVERSATION.format(language_name=lang_name)
        system = f"{system_prompt}\n\n{system_context}"

        messages = []
        for entry in conversation_history[-10:]:  # last 10 messages for context
            role = "assistant" if entry.direction == "outgoing" else "user"
            messages.append({"role": role, "content": entry.message_text})

        # Ensure messages alternate correctly and start with user
        cleaned = self._clean_message_history(messages)
        if not cleaned:
            cleaned = [{"role": "user", "content": f"{member.name} is waiting for a response."}]

        response = self.client.messages.create(
            model=self.model_conversation,
            max_tokens=500,
            temperature=0.7,
            system=system,
            messages=cleaned,
        )

        return response.content[0].text

    def _format_wishes(
        self, wishes: dict[str, list[str]], members: list[FamilyMember]
    ) -> str:
        member_names = {m.id: m.name for m in members}
        lines = []
        for member_id, wish_list in wishes.items():
            name = member_names.get(member_id, "Unknown")
            for w in wish_list:
                lines.append(f"- {name}: {w}")
        return "\n".join(lines) if lines else ""

    def _format_plan_for_revision(self, recipes: list[Recipe]) -> str:
        """Format the current plan as JSON so Claude can revise it properly."""
        plan_entries = []
        for r in recipes:
            plan_entries.append({
                "date": r.planned_date.isoformat(),
                "recipe": {
                    "name": r.name,
                    "description": r.description,
                    "servings": r.servings,
                    "prep_time_minutes": r.prep_time_minutes,
                    "cook_time_minutes": r.cook_time_minutes,
                    "cuisine": r.cuisine,
                    "tags": r.tags,
                    "ingredients": [
                        {"name": ing.name, "quantity": ing.quantity,
                         "unit": ing.unit, "category": ing.category}
                        for ing in r.ingredients
                    ],
                    "instructions": r.instructions,
                },
            })
        return json.dumps({"plan": plan_entries}, indent=2)

    def _parse_meal_plan(self, data: dict) -> MealPlan:
        recipes = []
        for entry in data.get("plan", []):
            r = entry["recipe"]
            ingredients = [
                Ingredient(
                    name=ing["name"],
                    quantity=ing.get("quantity", 0),
                    unit=ing.get("unit", ""),
                    category=ing.get("category", "other"),
                )
                for ing in r.get("ingredients", [])
            ]
            recipes.append(
                Recipe(
                    id=str(uuid.uuid4()),
                    name=r["name"],
                    description=r.get("description", ""),
                    planned_date=date.fromisoformat(entry["date"]),
                    servings=r.get("servings", 4),
                    prep_time_minutes=r.get("prep_time_minutes", 0),
                    cook_time_minutes=r.get("cook_time_minutes", 0),
                    cuisine=r.get("cuisine", ""),
                    tags=r.get("tags", []),
                    ingredients=ingredients,
                    instructions=r.get("instructions", ""),
                )
            )
        return MealPlan(
            recipes=recipes,
            reasoning=data.get("reasoning", ""),
        )

    def _clean_message_history(self, messages: list[dict]) -> list[dict]:
        """Ensure messages alternate roles and start with 'user'."""
        if not messages:
            return []
        cleaned = []
        for msg in messages:
            if cleaned and cleaned[-1]["role"] == msg["role"]:
                # Merge consecutive same-role messages
                cleaned[-1]["content"] += "\n" + msg["content"]
            else:
                cleaned.append(dict(msg))
        # Ensure starts with user
        if cleaned and cleaned[0]["role"] != "user":
            cleaned = cleaned[1:]
        return cleaned
