"""High-level iMessage handler combining reading and sending."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

from ..models import IncomingMessage
from .reader import IMessageReader
from .sender import send_imessage, send_to_group_chat

logger = logging.getLogger(__name__)


class IMessageHandler:
    """Combines polling for new messages and sending outbound messages."""

    def __init__(
        self,
        chat_db_path: Path,
        self_id: str = "",
        group_chat_id: str | None = None,
    ):
        self.reader = IMessageReader(chat_db_path)
        self.self_id = self_id  # Mac owner's phone/Apple ID
        self.group_chat_id = group_chat_id

    def initialize(self, last_rowid: int | None = None) -> None:
        """Initialize the reader. If last_rowid is provided, resume from there."""
        if last_rowid is not None:
            self.reader.last_rowid = last_rowid
        else:
            self.reader.initialize_last_rowid()

    def poll(self) -> list[IncomingMessage]:
        """Poll for new messages and resolve sender identity."""
        raw_messages = self.reader.poll_new_messages()
        resolved: list[IncomingMessage] = []

        for msg in raw_messages:
            if msg.is_from_me:
                # Sent from this Mac — sender is the Mac owner
                if self.self_id:
                    msg.sender_id = self.self_id
                else:
                    continue
            resolved.append(msg)

        return resolved

    async def send(self, recipient: str, message: str) -> bool:
        """Send an iMessage and skip past the outgoing message in chat.db."""
        result = await send_imessage(recipient, message)
        if result:
            # Wait briefly for Messages.app to write to chat.db, then
            # advance last_rowid past our own outgoing message so we
            # never re-process it on the next poll.
            await asyncio.sleep(0.5)
            self._advance_past_own_messages()
        return result

    async def send_to_group(self, message: str) -> bool:
        """Send to the configured group chat. Falls back to False if no group configured."""
        if not self.group_chat_id:
            logger.warning("No group chat configured, cannot send group message")
            return False
        result = await send_to_group_chat(self.group_chat_id, message)
        if result:
            await asyncio.sleep(0.5)
            self._advance_past_own_messages()
        return result

    async def broadcast(self, recipients: list[str], message: str) -> dict[str, bool]:
        """Send the same message to multiple recipients individually."""
        results = {}
        for recipient in recipients:
            results[recipient] = await send_imessage(recipient, message)
        # Advance once after all sends
        await asyncio.sleep(0.5)
        self._advance_past_own_messages()
        return results

    def _advance_past_own_messages(self) -> None:
        """Advance the reader's last_rowid to the current max in chat.db.

        This ensures the agent never re-processes messages it just sent.
        """
        try:
            conn = sqlite3.connect(str(self.reader.chat_db_path), timeout=5)
            try:
                row = conn.execute("SELECT MAX(ROWID) FROM message").fetchone()
                new_max = row[0] or 0
                if new_max > self.reader.last_rowid:
                    logger.debug(
                        "Advancing last_rowid %d -> %d (skipping own messages)",
                        self.reader.last_rowid, new_max,
                    )
                    self.reader.last_rowid = new_max
            finally:
                conn.close()
        except sqlite3.OperationalError:
            pass  # chat.db temporarily locked, will catch up next poll
