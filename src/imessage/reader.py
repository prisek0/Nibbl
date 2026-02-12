"""Read incoming iMessages by polling the macOS Messages chat.db."""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from ..models import IncomingMessage

logger = logging.getLogger(__name__)

# Apple's Core Data epoch starts at 2001-01-01 00:00:00 UTC
APPLE_EPOCH_OFFSET = 978307200


def _extract_text_from_attributed_body(blob: bytes) -> str | None:
    """Extract plain text from NSAttributedString blob (macOS Ventura+).

    When the 'text' column is NULL, the message content is stored in
    'attributedBody' as a typedstream-serialized NSAttributedString.
    The actual text appears after the marker bytes \\x01+ followed by
    a length byte encoding the text length.
    """
    try:
        # Primary method: find the \x01+ marker in the typedstream.
        # Format: \x01\x2B <length_byte> <text_bytes>
        marker = b"\x01+"
        idx = blob.find(marker)
        if idx != -1 and idx + 2 < len(blob):
            length_byte = blob[idx + 2]
            text_start = idx + 3

            if length_byte > 0 and text_start + length_byte <= len(blob):
                text_bytes = blob[text_start : text_start + length_byte]
                text = text_bytes.decode("utf-8", errors="replace").strip()
                if text:
                    return text

        # Fallback: look for readable text but aggressively filter metadata
        raw = blob.decode("latin-1", errors="ignore")
        matches = re.findall(r"[\x20-\x7e]{3,}", raw)
        candidates = []
        for m in matches:
            m = m.strip()
            # Skip known Apple/Cocoa metadata strings
            if (
                not m
                or m.startswith("NS")
                or m.startswith("__kIM")
                or m.startswith("streamtyped")
                or m in {"YES", "NO", "UTF", "nil"}
                or len(m) < 2
            ):
                continue
            candidates.append(m)
        if candidates:
            return max(candidates, key=len)
    except Exception:
        logger.debug("Failed to parse attributedBody", exc_info=True)
    return None


class IMessageReader:
    """Polls the macOS Messages SQLite database for new incoming messages."""

    def __init__(self, chat_db_path: Path):
        self.chat_db_path = chat_db_path
        self._last_rowid: int = 0

    @property
    def last_rowid(self) -> int:
        return self._last_rowid

    @last_rowid.setter
    def last_rowid(self, value: int) -> None:
        self._last_rowid = value

    def initialize_last_rowid(self) -> None:
        """Set last_rowid to the current max, so we only process new messages."""
        try:
            conn = sqlite3.connect(str(self.chat_db_path), timeout=5)
            try:
                row = conn.execute("SELECT MAX(ROWID) FROM message").fetchone()
                self._last_rowid = row[0] or 0
                logger.info("Initialized last_rowid to %d", self._last_rowid)
            finally:
                conn.close()
        except sqlite3.OperationalError:
            logger.warning("Could not read chat.db - check Full Disk Access permissions")
            self._last_rowid = 0

    def poll_new_messages(self) -> list[IncomingMessage]:
        """Fetch all incoming messages with ROWID > last_rowid.

        Returns new messages and updates last_rowid.
        """
        try:
            conn = sqlite3.connect(str(self.chat_db_path), timeout=5)
            conn.row_factory = sqlite3.Row
        except sqlite3.OperationalError:
            logger.warning("Could not connect to chat.db")
            return []

        try:
            cursor = conn.execute(
                """
                SELECT
                    m.ROWID,
                    m.text,
                    m.is_from_me,
                    m.date / 1000000000 + ? AS unix_timestamp,
                    m.attributedBody,
                    h.id AS handle_id,
                    c.chat_identifier,
                    c.display_name AS group_name
                FROM message m
                LEFT JOIN handle h ON m.handle_id = h.ROWID
                LEFT JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
                LEFT JOIN chat c ON cmj.chat_id = c.ROWID
                WHERE m.ROWID > ?
                ORDER BY m.ROWID ASC
                """,
                (APPLE_EPOCH_OFFSET, self._last_rowid),
            )

            messages: list[IncomingMessage] = []
            for row in cursor.fetchall():
                text = row["text"]
                is_from_me = bool(row["is_from_me"])

                # Handle attributedBody for macOS Ventura+
                if text is None and row["attributedBody"]:
                    text = _extract_text_from_attributed_body(row["attributedBody"])
                    if text:
                        logger.debug("Extracted from attributedBody: %r", text[:80])

                if not text:
                    self._last_rowid = max(self._last_rowid, row["ROWID"])
                    continue

                # For is_from_me=1, handle_id is the recipient (not the sender).
                # sender_id will be resolved by the handler using self_id config.
                # For is_from_me=0, handle_id is the actual sender.
                sender_id = row["handle_id"] or ""

                messages.append(
                    IncomingMessage(
                        rowid=row["ROWID"],
                        text=text.strip(),
                        sender_id=sender_id,
                        is_from_me=is_from_me,
                        chat_identifier=row["chat_identifier"],
                        group_name=row["group_name"],
                        timestamp=datetime.fromtimestamp(row["unix_timestamp"]),
                    )
                )
                self._last_rowid = max(self._last_rowid, row["ROWID"])

            if messages:
                logger.debug("Polled %d new message(s), last_rowid=%d", len(messages), self._last_rowid)
            return messages

        except sqlite3.OperationalError as e:
            logger.warning("Error reading chat.db: %s", e)
            return []
        finally:
            conn.close()
