import logging

logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("Backup skipped — database is hosted on PostgreSQL (Supabase)")
