"""Scheduling for automatic meal planning triggers."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import ScheduleConfig

logger = logging.getLogger(__name__)

DAY_MAP = {
    "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
    "fri": "fri", "sat": "sat", "sun": "sun",
    "0": "mon", "1": "tue", "2": "wed", "3": "thu",
    "4": "fri", "5": "sat", "6": "sun",
}


class MealPlanScheduler:
    """Schedules automatic meal planning sessions using APScheduler."""

    def __init__(self, schedule_config: ScheduleConfig):
        self.config = schedule_config
        self._scheduler = AsyncIOScheduler()
        self._callback = None

    def set_callback(self, callback) -> None:
        """Set the async callback to invoke when the schedule fires.

        The callback should be: async def callback() -> None
        """
        self._callback = callback

    def start(self) -> None:
        """Start the scheduler if enabled."""
        if not self.config.enabled:
            logger.info("Scheduler is disabled")
            return

        if not self._callback:
            raise RuntimeError("No callback set. Call set_callback() first.")

        day = DAY_MAP.get(self.config.day_of_week.lower(), self.config.day_of_week)

        trigger = CronTrigger(
            day_of_week=day,
            hour=self.config.hour,
            minute=self.config.minute,
        )

        self._scheduler.add_job(
            self._callback,
            trigger=trigger,
            id="weekly_meal_plan",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            "Scheduler started: runs every %s at %02d:%02d",
            day, self.config.hour, self.config.minute,
        )

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
