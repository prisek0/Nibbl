"""FoodAgend — AI-powered family dinner planning agent.

Entry point: loads config, wires up all components, and runs the main polling loop.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

import anthropic

from .config import Config
from .conversation.manager import ConversationManager
from .database import Database
from .imessage.handler import IMessageHandler
from .orchestrator import Orchestrator
from .picnic.cart_filler import CartFiller
from .picnic.client import PicnicClient
from .planner.meal_planner import MealPlanner
from .planner.preference_engine import PreferenceEngine
from .scheduler import MealPlanScheduler
from .models import FamilyMember, MemberRole

logger = logging.getLogger("foodagend")


def _handle_signal(sig: signal.Signals, shutdown_event: asyncio.Event) -> None:
    logger.info("Received %s, shutting down...", sig.name)
    shutdown_event.set()


def setup_logging(config: Config) -> None:
    """Configure logging to both file and console."""
    log_path = Path(config.logging.file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout),
        ],
    )


def sync_family_members(config: Config, db: Database) -> None:
    """Sync configured family members into the database."""
    for member_cfg in config.family_members:
        existing = db.get_member_by_imessage_id(member_cfg.imessage_id)
        if existing:
            existing.name = member_cfg.name
            existing.role = MemberRole(member_cfg.role)
            db.upsert_family_member(existing)
        else:
            member = FamilyMember.create(
                name=member_cfg.name,
                imessage_id=member_cfg.imessage_id,
                role=MemberRole(member_cfg.role),
            )
            db.upsert_family_member(member)
    logger.info("Synced %d family member(s)", len(config.family_members))


def build_orchestrator(config: Config) -> Orchestrator:
    """Wire up all components and return the orchestrator."""
    db = Database(config.db_path)

    # Sync family members from config
    sync_family_members(config, db)

    # iMessage handler
    imessage = IMessageHandler(
        chat_db_path=config.imessage.resolved_chat_db_path,
        self_id=config.imessage.self_id,
        group_chat_id=config.imessage.group_chat_name,
    )

    # Claude API client
    claude = anthropic.Anthropic(api_key=config.anthropic_api_key)

    # Meal planner
    planner = MealPlanner(
        client=claude,
        model_planning=config.claude.model_planning,
        model_conversation=config.claude.model_conversation,
        model_extraction=config.claude.model_extraction,
        db=db,
    )

    # Preference engine
    preference_engine = PreferenceEngine(
        client=claude,
        model=config.claude.model_extraction,
        db=db,
    )

    # Conversation manager
    conversation = ConversationManager(db=db, planner=planner)

    # Picnic client and cart filler
    picnic = PicnicClient(
        username=config.picnic_username,
        password=config.picnic_password,
        country_code=config.picnic.country_code,
    )
    cart_filler = CartFiller(
        picnic=picnic,
        claude=claude,
        model=config.claude.model_extraction,
    )

    return Orchestrator(
        config=config,
        db=db,
        imessage=imessage,
        planner=planner,
        preference_engine=preference_engine,
        conversation=conversation,
        cart_filler=cart_filler,
    )


async def run(config: Config) -> None:
    """Main event loop: poll for messages and process them."""
    orchestrator = build_orchestrator(config)

    # Initialize iMessage reader — on first run, skip all existing messages
    saved_rowid = orchestrator.db.get_state("last_rowid")
    if saved_rowid:
        orchestrator.imessage.initialize(last_rowid=int(saved_rowid))
    else:
        orchestrator.imessage.initialize()  # sets to current max ROWID

    # Resume any active session
    orchestrator.load_active_session()

    # Login to Picnic
    if config.picnic_username and config.picnic_password:
        try:
            orchestrator.cart_filler.picnic.login()
            logger.info("Picnic login successful")
        except Exception as e:
            logger.warning("Picnic login failed (will retry when needed): %s", e)

    # Start scheduler
    scheduler = MealPlanScheduler(config.schedule)
    scheduler.set_callback(orchestrator.start_session)
    scheduler.start()

    # Graceful shutdown via asyncio-native signal handling
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s, shutdown_event))

    logger.info("FoodAgend is running. Polling every %ds. Press Ctrl+C to stop.",
                config.agent.poll_interval_seconds)

    try:
        while not shutdown_event.is_set():
            # Poll for new messages
            messages = orchestrator.imessage.poll()

            for msg in messages:
                try:
                    await orchestrator.handle_incoming_message(msg)
                except Exception:
                    logger.error("Error handling message %d", msg.rowid, exc_info=True)

            # Check for timed transitions
            try:
                await orchestrator.check_timeouts()
            except Exception:
                logger.error("Error checking timeouts", exc_info=True)

            # Persist last processed rowid
            orchestrator.db.set_state(
                "last_rowid",
                str(orchestrator.imessage.reader.last_rowid),
            )

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=config.agent.poll_interval_seconds)
            except asyncio.TimeoutError:
                pass  # Normal — poll interval elapsed, loop again
    finally:
        scheduler.stop()
        logger.info("FoodAgend stopped.")


def main() -> None:
    """CLI entry point."""
    config_path = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        config = Config.load(config_path)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Create a config.toml or set FOODAGEND_CONFIG environment variable.")
        sys.exit(1)

    if not config.anthropic_api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    setup_logging(config)
    asyncio.run(run(config))


if __name__ == "__main__":
    main()
