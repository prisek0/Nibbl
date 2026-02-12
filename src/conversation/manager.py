"""Conversation manager — routes messages based on sender and session state."""

from __future__ import annotations

import logging

from ..database import Database
from ..models import (
    ConversationEntry,
    FamilyMember,
    IncomingMessage,
    MealPlanSession,
    MemberRole,
)
from ..planner.meal_planner import MealPlanner

logger = logging.getLogger(__name__)

TRIGGER_PHRASES = [
    "plan dinner", "plan eten", "wat eten we", "meal plan",
    "boodschappen", "start planning", "plan meals", "weekmenu",
    "dinner plan", "plan het eten", "plan food", "plan the food",
    "what's for dinner", "what are we eating",
]


def is_trigger_message(text: str) -> bool:
    """Quick heuristic check for trigger messages."""
    text_lower = text.lower().strip()
    return any(phrase in text_lower for phrase in TRIGGER_PHRASES)


class ConversationManager:
    """Routes incoming messages to appropriate handlers based on context."""

    def __init__(self, db: Database, planner: MealPlanner):
        self.db = db
        self.planner = planner

    def resolve_sender(self, msg: IncomingMessage) -> FamilyMember | None:
        """Look up a family member by their iMessage sender ID."""
        return self.db.get_member_by_imessage_id(msg.sender_id)

    async def classify(
        self,
        message_text: str,
        session: MealPlanSession | None,
        member: FamilyMember,
    ) -> dict:
        """Classify a message's intent using Claude."""
        state = session.state.value if session else "idle"
        return await self.planner.classify_message(
            message_text=message_text,
            current_state=state,
            sender_role=member.role.value,
        )

    def log_incoming(
        self,
        msg: IncomingMessage,
        member: FamilyMember,
        session: MealPlanSession | None,
    ) -> None:
        """Log an incoming message to the conversation log."""
        self.db.log_conversation(
            ConversationEntry(
                session_id=session.id if session else None,
                member_id=member.id,
                direction="incoming",
                message_text=msg.text,
                imessage_rowid=msg.rowid,
            )
        )

    def log_outgoing(
        self,
        recipient_id: str,
        message_text: str,
        session: MealPlanSession | None,
    ) -> None:
        """Log an outgoing message."""
        self.db.log_conversation(
            ConversationEntry(
                session_id=session.id if session else None,
                member_id=recipient_id,
                direction="outgoing",
                message_text=message_text,
            )
        )

    def get_context_for_reply(
        self,
        session: MealPlanSession | None,
        member: FamilyMember,
    ) -> list[ConversationEntry]:
        """Get recent conversation history for generating a reply."""
        if not session:
            return []
        return self.db.get_conversation_history(session.id, member.id, limit=10)

    def is_parent(self, member: FamilyMember) -> bool:
        return member.role == MemberRole.PARENT

    def get_first_parent(self) -> FamilyMember | None:
        """Get the first parent (primary contact for approvals)."""
        parents = self.db.get_parents()
        return parents[0] if parents else None
