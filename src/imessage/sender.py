"""Send iMessages via AppleScript."""

from __future__ import annotations

import asyncio
import logging
import subprocess

logger = logging.getLogger(__name__)


def _escape_for_applescript(text: str) -> str:
    """Escape special characters for embedding in AppleScript strings."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


async def send_imessage(recipient: str, message: str) -> bool:
    """Send an iMessage to a phone number or email address.

    Args:
        recipient: Phone number (e.g., "+31612345678") or Apple ID email.
        message: The message text to send.

    Returns:
        True if the message was sent successfully.
    """
    escaped = _escape_for_applescript(message)

    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{recipient}" of targetService
        send "{escaped}" to targetBuddy
    end tell
    '''

    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            logger.error(
                "Failed to send iMessage to %s: %s",
                recipient,
                stderr.decode().strip(),
            )
            return False

        logger.info("Sent iMessage to %s (%d chars)", recipient, len(message))
        return True

    except asyncio.TimeoutError:
        logger.error("Timeout sending iMessage to %s", recipient)
        return False
    except Exception:
        logger.error("Error sending iMessage to %s", recipient, exc_info=True)
        return False


async def send_to_group_chat(chat_id: str, message: str) -> bool:
    """Send a message to a group chat by its chat identifier.

    Args:
        chat_id: The chat identifier (e.g., "chat123456789").
        message: The message text to send.

    Returns:
        True if the message was sent successfully.
    """
    escaped = _escape_for_applescript(message)

    script = f'''
    tell application "Messages"
        set targetChat to a reference to text chat id "{chat_id}"
        send "{escaped}" to targetChat
    end tell
    '''

    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0:
            logger.error(
                "Failed to send to group chat %s: %s",
                chat_id,
                stderr.decode().strip(),
            )
            return False

        logger.info("Sent message to group chat %s (%d chars)", chat_id, len(message))
        return True

    except asyncio.TimeoutError:
        logger.error("Timeout sending to group chat %s", chat_id)
        return False
    except Exception:
        logger.error("Error sending to group chat %s", chat_id, exc_info=True)
        return False
