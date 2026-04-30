from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bot.config.settings import settings
from bot.core.logger import get_logger
from bot.jobs.compliance_scan import daily_compliance_scan
from bot.jobs.grace_restoration import grace_restoration_watcher
from bot.jobs.grace_watcher import grace_expiry_watcher

logger = get_logger(__name__)

BROADCAST_JOBSTORE = "broadcasts"


def setup_scheduler() -> AsyncIOScheduler:
    """Create and configure APScheduler with two jobstores.

    - "default" (MemoryJobStore): periodic jobs that take a non-picklable Bot
      argument and re-register on every startup with replace_existing=True.
    - "broadcasts" (RedisJobStore): user-scheduled broadcasts. Args must be
      picklable; the runner pulls Bot/BroadcastService from the runtime
      singleton (bot.services.broadcast_runtime).
    """
    scheduler = AsyncIOScheduler(
        jobstores={
            "default": MemoryJobStore(),
            BROADCAST_JOBSTORE: RedisJobStore(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                jobs_key="apscheduler.broadcasts.jobs",
                run_times_key="apscheduler.broadcasts.run_times",
            ),
        },
        timezone="UTC",
    )
    logger.info("scheduler_created")
    return scheduler


async def start_scheduler(scheduler: AsyncIOScheduler, bot) -> None:
    """Start scheduler and register periodic jobs in the default (memory) store."""

    scheduler.add_job(
        daily_compliance_scan,
        trigger=CronTrigger(
            hour=settings.compliance_scan_hour,
            minute=settings.compliance_scan_minute,
        ),
        args=[bot],
        id="daily_compliance_scan",
        replace_existing=True,
        max_instances=1,
        jobstore="default",
    )

    scheduler.add_job(
        grace_expiry_watcher,
        trigger=IntervalTrigger(minutes=settings.GRACE_WATCHER_INTERVAL_MINUTES),
        args=[bot],
        id="grace_expiry_watcher",
        replace_existing=True,
        max_instances=1,
        jobstore="default",
    )

    scheduler.add_job(
        grace_restoration_watcher,
        trigger=IntervalTrigger(minutes=settings.GRACE_RESTORATION_INTERVAL_MINUTES),
        args=[bot],
        id="grace_restoration_watcher",
        replace_existing=True,
        max_instances=1,
        jobstore="default",
    )

    scheduler.start()
    logger.info("scheduler_started", job_count=len(scheduler.get_jobs()))


async def stop_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Stop scheduler gracefully."""
    scheduler.shutdown(wait=True)
    logger.info("scheduler_stopped")
