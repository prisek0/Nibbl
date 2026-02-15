"""Agent orchestrator — the central state machine coordinating all components."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .config import Config
from .conversation.manager import ConversationManager, is_trigger_message
from .database import Database
from .imessage.handler import IMessageHandler
from .models import (
    FamilyMember,
    IncomingMessage,
    MealHistoryEntry,
    MealPlanSession,
    MemberRole,
    SessionState,
)
from .picnic.cart_filler import CartFiller
from .planner.formatter import (
    format_cart_report,
    format_full_ingredient_list,
    format_meal_plan,
    format_pantry_check,
)
from .exporter import MarkdownExporter
from .planner.meal_planner import MealPlanner
from .planner.pantry_matcher import match_pantry_items
from .planner.preference_engine import PreferenceEngine

logger = logging.getLogger(__name__)


# Bilingual messages keyed by (key, language)
MESSAGES = {
    "ask_preferences": {
        "nl": (
            "Hoi! Tijd om het eten te plannen. "
            "Wat willen jullie graag eten de komende dagen?\n\n"
            "Stuur je wensen en ik maak er een lekker weekmenu van!"
        ),
        "en": (
            "Hi! Time to plan dinner. "
            "What would you like to eat the coming days?\n\n"
            "Send me your wishes and I'll create a tasty weekly menu!"
        ),
    },
    "thanks_preference": {
        "nl": "Bedankt {name}! Ik neem je wensen mee.",
        "en": "Thanks {name}! I'll include your wishes.",
    },
    "all_responded": {
        "nl": "Iedereen heeft gereageerd! Ik ga het menu maken...",
        "en": "Everyone responded! I'm creating the menu...",
    },
    "ask_approval": {
        "nl": "Ziet dit er goed uit? Stuur 'ok' om door te gaan, of vertel me wat je wilt aanpassen.",
        "en": "Does this look good? Send 'ok' to proceed, or tell me what you'd like to change.",
    },
    "plan_approved": {
        "nl": "Top! Ik ga de boodschappenlijst maken.",
        "en": "Great! I'll compile the shopping list.",
    },
    "full_rejection": {
        "nl": "Oke, ik maak een heel nieuw menu. Even geduld...",
        "en": "Okay, I'll create a completely new menu. One moment...",
    },
    "adjusting_plan": {
        "nl": "Ik pas het menu aan. Even geduld...",
        "en": "I'm adjusting the menu. One moment...",
    },
    "revision_failed": {
        "nl": "Sorry, dat lukte niet. Probeer het opnieuw of stuur 'ok' om door te gaan.",
        "en": "Sorry, that didn't work. Try again or send 'ok' to proceed.",
    },
    "plan_failed": {
        "nl": "Sorry, er ging iets mis bij het maken van het menu. Ik probeer het later opnieuw.",
        "en": "Sorry, something went wrong creating the menu. I'll try again later.",
    },
    "filling_cart": {
        "nl": "Ik ga de boodschappen aan je Picnic mandje toevoegen...",
        "en": "I'm adding the groceries to your Picnic cart...",
    },
    "pantry_marked": {
        "nl": "Begrepen! {count} dingen sla ik over. Ik ga de rest toevoegen aan Picnic...",
        "en": "Got it! Skipping {count} items. Adding the rest to Picnic...",
    },
    "pantry_none": {
        "nl": "Oke! Ik voeg alles toe aan je Picnic mandje...",
        "en": "Okay! Adding everything to your Picnic cart...",
    },
    "session_active": {
        "nl": "Er loopt al een planning! Stuur 'stop' om die te annuleren.",
        "en": "There's already a planning session active! Send 'stop' to cancel it.",
    },
    "cancelled": {
        "nl": "Planning geannuleerd. Stuur 'plan eten' om opnieuw te beginnen.",
        "en": "Planning cancelled. Send 'plan dinner' to start again.",
    },
    "picnic_error": {
        "nl": "Er ging iets mis met Picnic: {error}. Probeer het handmatig.",
        "en": "Something went wrong with Picnic: {error}. Please try manually.",
    },
}


class Orchestrator:
    """Coordinates the meal planning workflow through a state machine."""

    def __init__(
        self,
        config: Config,
        db: Database,
        imessage: IMessageHandler,
        planner: MealPlanner,
        preference_engine: PreferenceEngine,
        conversation: ConversationManager,
        cart_filler: CartFiller,
    ):
        self.config = config
        self.db = db
        self.imessage = imessage
        self.planner = planner
        self.preference_engine = preference_engine
        self.conversation = conversation
        self.cart_filler = cart_filler
        self.exporter = MarkdownExporter(config.export, lang=config.agent.language)
        self.session: MealPlanSession | None = None
        self._lang = config.agent.language  # "nl" or "en"

    def _msg(self, key: str, **kwargs) -> str:
        """Get a localized message string."""
        templates = MESSAGES.get(key, {})
        text = templates.get(self._lang, templates.get("en", f"[{key}]"))
        return text.format(**kwargs) if kwargs else text

    def load_active_session(self) -> None:
        """Resume an active session from the database (after restart)."""
        self.session = self.db.get_active_session()
        if self.session:
            logger.info(
                "Resumed active session %s in state %s",
                self.session.id,
                self.session.state.value,
            )

    async def handle_incoming_message(self, msg: IncomingMessage) -> None:
        """Process a single incoming iMessage."""
        member = self.conversation.resolve_sender(msg)
        if not member:
            logger.info("Ignoring message from unknown sender: %s", msg.sender_id)
            return

        logger.info(
            "Message from %s: %s (session=%s)",
            member.name, msg.text[:60], self.session.state.value if self.session else "idle",
        )

        # Log the message
        self.conversation.log_incoming(msg, member, self.session)

        if self.session:
            await self._handle_session_message(member, msg)
        else:
            # Extract preferences even outside sessions (passive learning)
            await self.preference_engine.extract_and_store(member, msg.text)
            await self._handle_idle_message(member, msg)

    async def check_timeouts(self) -> None:
        """Check for timed state transitions."""
        if not self.session:
            return

        elapsed = datetime.now() - self.session.state_entered_at

        if (
            self.session.state == SessionState.COLLECTING_PREFERENCES
            and elapsed > timedelta(hours=self.config.agent.preference_timeout_hours)
        ):
            logger.info("Preference collection timed out, generating plan")
            await self._enter_generating_plan()

        elif (
            self.session.state == SessionState.CHECKING_PANTRY
            and elapsed > timedelta(hours=self.config.agent.pantry_timeout_hours)
        ):
            logger.info("Pantry check timed out, filling cart with all items")
            await self._enter_filling_cart()

    async def start_session(self, triggered_by: FamilyMember | None = None) -> None:
        """Start a new meal planning session."""
        if self.session and self.session.state not in (
            SessionState.IDLE,
            SessionState.COMPLETED,
        ):
            logger.warning("Session already active, ignoring new trigger")
            if triggered_by:
                await self.imessage.send(
                    triggered_by.imessage_id,
                    self._msg("session_active"),
                )
            return

        self.session = MealPlanSession.create(
            triggered_by=triggered_by.id if triggered_by else None
        )
        logger.info("Started new session %s", self.session.id)
        await self._enter_collecting_preferences()

    async def _handle_idle_message(
        self, member: FamilyMember, msg: IncomingMessage
    ) -> None:
        """Handle a message when no session is active."""
        if member.role == MemberRole.PARENT and is_trigger_message(msg.text):
            logger.info("Trigger phrase detected from %s", member.name)
            await self.start_session(triggered_by=member)
            return

        # Use Claude to check if it's a trigger
        classification = await self.conversation.classify(msg.text, None, member)
        logger.info("Classification for '%s': %s", msg.text[:40], classification)
        if classification.get("intent") == "trigger" and member.role == MemberRole.PARENT:
            await self.start_session(triggered_by=member)

    async def _handle_session_message(
        self, member: FamilyMember, msg: IncomingMessage
    ) -> None:
        """Route a message based on the current session state."""
        # Check for cancel from parent
        classification = await self.conversation.classify(msg.text, self.session, member)
        intent = classification.get("intent", "other")

        if intent == "cancel" and member.role == MemberRole.PARENT:
            await self._cancel_session(member)
            return

        match self.session.state:
            case SessionState.COLLECTING_PREFERENCES:
                await self._handle_preference_message(member, msg, intent)
            case SessionState.AWAITING_APPROVAL:
                if member.role == MemberRole.PARENT:
                    await self._handle_approval_message(member, msg, intent)
            case SessionState.CHECKING_PANTRY:
                if member.role == MemberRole.PARENT:
                    await self._handle_pantry_message(member, msg, intent)
            case _:
                # In non-interactive states, acknowledge but don't act
                pass

    # --- State transitions ---

    async def _enter_collecting_preferences(self) -> None:
        """Transition to COLLECTING_PREFERENCES: ask everyone for wishes."""
        self.session.transition_to(SessionState.COLLECTING_PREFERENCES)
        self.session.collected_wishes = {}
        self.session.members_responded = set()
        self.db.save_session(self.session)

        members = self.db.get_all_family_members()
        message = self._msg("ask_preferences")

        for member in members:
            await self._send_and_log(member.imessage_id, message, member.id)

    async def _enter_generating_plan(self) -> None:
        """Transition to GENERATING_PLAN: generate the meal plan."""
        self.session.transition_to(SessionState.GENERATING_PLAN)
        self.db.save_session(self.session)

        members = self.db.get_all_family_members()
        all_prefs = self.preference_engine.get_all_formatted(members)

        try:
            plan = await self.planner.generate_meal_plan(
                members=members,
                all_preferences=all_prefs,
                specific_wishes=self.session.collected_wishes,
                num_days=self.config.agent.plan_days,
                lang=self._lang,
            )
        except Exception as e:
            logger.error("Failed to generate meal plan: %s", e, exc_info=True)
            parent = self.conversation.get_first_parent()
            if parent:
                await self._send_and_log(
                    parent.imessage_id,
                    self._msg("plan_failed"),
                    parent.id,
                )
            return

        # Save recipes
        self.session.meal_plan = plan
        for recipe in plan.recipes:
            recipe.session_id = self.session.id
            self.db.save_recipe(recipe)

        # Set plan date range
        if plan.recipes:
            self.session.plan_start_date = plan.recipes[0].planned_date
            self.session.plan_end_date = plan.recipes[-1].planned_date

        # Present to parent for approval
        await self._enter_awaiting_approval(plan)

    async def _enter_awaiting_approval(self, plan=None) -> None:
        """Transition to AWAITING_APPROVAL: send plan to parent."""
        self.session.transition_to(SessionState.AWAITING_APPROVAL)
        self.db.save_session(self.session)

        if plan is None:
            recipes = self.db.get_recipes_for_session(self.session.id)
        else:
            recipes = plan.recipes

        formatted = format_meal_plan(recipes, lang=self._lang)
        parent = self.conversation.get_first_parent()
        if parent:
            await self._send_and_log(parent.imessage_id, formatted, parent.id)
            await self._send_and_log(
                parent.imessage_id,
                self._msg("ask_approval"),
                parent.id,
            )

    async def _enter_compiling_ingredients(self) -> None:
        """Transition to COMPILING_INGREDIENTS: mark recipes approved, export, list ingredients."""
        self.session.transition_to(SessionState.COMPILING_INGREDIENTS)
        self.db.mark_recipes_approved(self.session.id)
        self.db.save_session(self.session)

        # Export approved recipes and meal plan to markdown
        if self.config.export.enabled:
            recipes = self.db.get_recipes_for_session(self.session.id)
            try:
                self.exporter.export_session(recipes, self.session)
            except Exception as e:
                logger.error("Failed to export markdown: %s", e, exc_info=True)

        # Move to pantry check
        await self._enter_checking_pantry()

    async def _enter_checking_pantry(self) -> None:
        """Transition to CHECKING_PANTRY: ask parent about available items."""
        self.session.transition_to(SessionState.CHECKING_PANTRY)
        self.db.save_session(self.session)

        recipes = self.db.get_recipes_for_session(self.session.id)
        all_ingredients = [ing for r in recipes for ing in r.ingredients]

        pantry_msg = format_pantry_check(all_ingredients, lang=self._lang)
        if not pantry_msg:
            # No pantry items to check, skip to cart
            await self._enter_filling_cart()
            return

        full_list = format_full_ingredient_list(recipes, lang=self._lang)
        parent = self.conversation.get_first_parent()
        if parent:
            await self._send_and_log(parent.imessage_id, full_list, parent.id)
            await self._send_and_log(parent.imessage_id, pantry_msg, parent.id)

    async def _enter_filling_cart(self) -> None:
        """Transition to FILLING_CART: add remaining ingredients to Picnic cart."""
        self.session.transition_to(SessionState.FILLING_CART)
        self.db.save_session(self.session)

        parent = self.conversation.get_first_parent()
        if parent:
            await self._send_and_log(
                parent.imessage_id,
                self._msg("filling_cart"),
                parent.id,
            )

        recipes = self.db.get_recipes_for_session(self.session.id)
        all_ingredients = [ing for r in recipes for ing in r.ingredients]

        try:
            report = await self.cart_filler.fill_cart(all_ingredients)
        except Exception as e:
            logger.error("Failed to fill cart: %s", e, exc_info=True)
            if parent:
                await self._send_and_log(
                    parent.imessage_id,
                    self._msg("picnic_error", error=str(e)),
                    parent.id,
                )
            await self._enter_completed()
            return

        # Update original DB ingredients with Picnic match info from merged results
        added_by_name = {
            ing.name.lower(): ing for ing, _ in report.added
        }
        for ing in all_ingredients:
            match = added_by_name.get(ing.name.lower())
            if match:
                ing.picnic_product_id = match.picnic_product_id
                ing.picnic_product_name = match.picnic_product_name
                ing.picnic_added_to_cart = match.picnic_added_to_cart
                ing.search_status = match.search_status
                self.db.update_ingredient(ing)

        report_msg = format_cart_report(report, lang=self._lang)
        if parent:
            await self._send_and_log(parent.imessage_id, report_msg, parent.id)

        await self._enter_completed()

    async def _enter_completed(self) -> None:
        """Transition to COMPLETED: archive session and record meal history."""
        self.session.transition_to(SessionState.COMPLETED)
        self.db.save_session(self.session)

        # Record meal history for variety tracking
        recipes = self.db.get_recipes_for_session(self.session.id)
        for recipe in recipes:
            # Guess main protein from tags/ingredients
            protein = self._guess_protein(recipe)
            self.db.add_meal_history(
                MealHistoryEntry(
                    recipe_name=recipe.name,
                    cuisine=recipe.cuisine,
                    main_protein=protein,
                    tags=recipe.tags,
                    cooked_date=recipe.planned_date,
                    session_id=self.session.id,
                )
            )

        logger.info("Session %s completed", self.session.id)
        self.session = None

    async def _cancel_session(self, member: FamilyMember) -> None:
        """Cancel the active session."""
        if self.session:
            self.session.transition_to(SessionState.COMPLETED)
            self.db.save_session(self.session)
            self.session = None
        await self._send_and_log(
            member.imessage_id,
            self._msg("cancelled"),
            member.id,
        )

    # --- Message handlers per state ---

    async def _handle_preference_message(
        self, member: FamilyMember, msg: IncomingMessage, intent: str
    ) -> None:
        """Handle a message during preference collection."""
        # Extract wishes
        _, wishes = await self.preference_engine.extract_and_store(member, msg.text)

        # Track response
        self.session.members_responded.add(member.id)
        if wishes:
            self.session.collected_wishes.setdefault(member.id, []).extend(wishes)

        # Acknowledge
        await self._send_and_log(
            member.imessage_id,
            self._msg("thanks_preference", name=member.name),
            member.id,
        )

        # Check if parent says "go ahead"
        if intent == "trigger" and member.role == MemberRole.PARENT:
            await self._enter_generating_plan()
            return

        # Check if all members have responded
        all_members = self.db.get_all_family_members()
        if self.session.members_responded >= {m.id for m in all_members}:
            await self._send_and_log(
                member.imessage_id,
                self._msg("all_responded"),
                member.id,
            )
            await self._enter_generating_plan()

    async def _handle_approval_message(
        self, member: FamilyMember, msg: IncomingMessage, intent: str
    ) -> None:
        """Handle a message during approval phase."""
        if intent == "approval":
            await self._send_and_log(
                member.imessage_id,
                self._msg("plan_approved"),
                member.id,
            )
            await self._enter_compiling_ingredients()

        elif intent == "rejection":
            await self._send_and_log(
                member.imessage_id,
                self._msg("full_rejection"),
                member.id,
            )
            self.db.delete_recipes_for_session(self.session.id)
            await self._enter_generating_plan()

        elif intent == "change_request":
            await self._send_and_log(
                member.imessage_id,
                self._msg("adjusting_plan"),
                member.id,
            )
            # Revise the plan — keep old recipes until revision succeeds
            recipes = self.db.get_recipes_for_session(self.session.id)
            try:
                revised = await self.planner.revise_meal_plan(recipes, msg.text)
                if revised.recipes:
                    self.db.delete_recipes_for_session(self.session.id)
                    for recipe in revised.recipes:
                        recipe.session_id = self.session.id
                        self.db.save_recipe(recipe)
                    self.session.meal_plan = revised
                    await self._enter_awaiting_approval(revised)
                else:
                    # Revision returned empty — re-show existing plan
                    await self._enter_awaiting_approval()
            except Exception as e:
                logger.error("Failed to revise plan: %s", e, exc_info=True)
                await self._send_and_log(
                    member.imessage_id,
                    self._msg("revision_failed"),
                    member.id,
                )

    async def _handle_pantry_message(
        self, member: FamilyMember, msg: IncomingMessage, intent: str
    ) -> None:
        """Handle parent's response about what they already have at home."""
        recipes = self.db.get_recipes_for_session(self.session.id)
        all_ingredients = [ing for r in recipes for ing in r.ingredients]

        # Use Claude to fuzzy-match the parent's message to ingredient names
        matched_names = await match_pantry_items(
            self.planner.client,
            self.planner.model_extraction,
            msg.text,
            all_ingredients,
        )

        marked = 0
        matched_lower = {n.lower() for n in matched_names}
        for ing in all_ingredients:
            if ing.name.lower() in matched_lower:
                ing.already_available = True
                self.db.update_ingredient(ing)
                marked += 1

        if marked > 0:
            await self._send_and_log(
                member.imessage_id,
                self._msg("pantry_marked", count=marked),
                member.id,
            )
        else:
            await self._send_and_log(
                member.imessage_id,
                self._msg("pantry_none"),
                member.id,
            )

        await self._enter_filling_cart()

    # --- Helpers ---

    async def _send_and_log(
        self, recipient_id: str, message: str, member_id: str
    ) -> None:
        """Send an iMessage and log it."""
        await self.imessage.send(recipient_id, message)
        self.conversation.log_outgoing(member_id, message, self.session)

    def _guess_protein(self, recipe) -> str | None:
        """Guess the main protein from recipe tags and ingredients."""
        proteins = {"chicken", "kip", "beef", "rund", "pork", "varken", "fish",
                     "vis", "zalm", "salmon", "tofu", "garnalen", "shrimp",
                     "gehakt", "lamb", "lam", "tonijn", "tuna"}
        # Check tags
        for tag in recipe.tags:
            if tag.lower() in proteins:
                return tag.lower()
        # Check ingredient names
        for ing in recipe.ingredients:
            name_lower = ing.name.lower()
            for p in proteins:
                if p in name_lower:
                    return p
        if "vegetarian" in [t.lower() for t in recipe.tags] or "vegetarisch" in [t.lower() for t in recipe.tags]:
            return "vegetarisch"
        return None
