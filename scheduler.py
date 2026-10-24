"""
Shared APScheduler instance used by all timed features (broadcasts, AI agent, etc.).
Start it once from main.py; each feature module registers its own jobs.
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            timezone="Asia/Taipei",
            job_defaults={"misfire_grace_time": 600, "coalesce": True, "max_instances": 1},
        )
    return _scheduler


def start() -> None:
    s = get()
    if not s.running:
        s.start()
        logger.info("APScheduler started (timezone=Asia/Taipei)")


def shutdown() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler shutdown")
    _scheduler = None
