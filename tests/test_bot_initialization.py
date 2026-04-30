"""End-to-end smoke test: initialize all bot components except start_polling."""

from __future__ import annotations

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage
from aiogram_broadcast import BroadcastService
from aiogram_broadcast.models import SubscriberState

from bot.config.settings import settings
from bot.core.db import db_manager
from bot.core.redis_client import redis_manager
from bot.jobs.scheduler import (
    BROADCAST_JOBSTORE,
    setup_scheduler,
    start_scheduler,
    stop_scheduler,
)
from bot.services.broadcast_runtime import get_bot, get_service, set_runtime
from bot.services.broadcast_storage import SQLAlchemyBroadcastStorage


@pytest.fixture(scope="module", autouse=True)
async def services():
    await db_manager.connect()
    await redis_manager.connect()
    yield
    await redis_manager.disconnect()
    await db_manager.disconnect()


async def test_broadcast_service_construction():
    bot = Bot(
        token="123456:test_dummy_token_for_init_only",
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    storage = SQLAlchemyBroadcastStorage(db_manager)
    service = BroadcastService(
        bot,
        storage,
        rate_limit=settings.BROADCAST_RPS_DELAY,
        max_retries=settings.BROADCAST_MAX_RETRIES,
    )
    set_runtime(bot, service)

    assert get_bot() is bot
    assert get_service() is service
    assert service.bot is bot
    assert service.storage is storage
    assert service.is_broadcasting is False

    # Live count from Postgres (no users present at this moment ⇒ count >= 0)
    count = await service.get_subscriber_count(only_active=True)
    assert count >= 0

    await bot.session.close()


async def test_scheduler_lifecycle():
    """Scheduler creates with two jobstores; periodic jobs go to default (memory),
    broadcast jobs to RedisJobStore."""
    bot = Bot(
        token="123456:test_dummy_token_for_init_only",
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    scheduler = setup_scheduler()
    assert "default" in scheduler._jobstores
    assert BROADCAST_JOBSTORE in scheduler._jobstores

    await start_scheduler(scheduler, bot)

    # Default jobstore — three periodic jobs
    default_jobs = scheduler.get_jobs(jobstore="default")
    assert len(default_jobs) == 3
    job_ids = {j.id for j in default_jobs}
    assert job_ids == {
        "daily_compliance_scan",
        "grace_expiry_watcher",
        "grace_restoration_watcher",
    }

    # Broadcast jobstore — empty initially
    broadcast_jobs = scheduler.get_jobs(jobstore=BROADCAST_JOBSTORE)
    assert broadcast_jobs == []

    await stop_scheduler(scheduler)
    await bot.session.close()


async def test_redis_jobstore_round_trip():
    """Schedule a dummy broadcast job in Redis, verify retrieval, then cancel."""
    from datetime import datetime, timedelta, timezone

    from apscheduler.triggers.date import DateTrigger

    from bot.jobs.broadcast_runner import run_broadcast

    bot = Bot(
        token="123456:test_dummy_token_for_init_only",
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    scheduler = setup_scheduler()
    await start_scheduler(scheduler, bot)

    job_id = "broadcast_test_round_trip"
    run_at = datetime.now(timezone.utc) + timedelta(hours=1)
    msg_data = {
        "chat": {"id": 1, "type": "private"},
        "message_id": 1,
        "date": 0,
        "text": "x",
    }
    scheduler.add_job(
        func=run_broadcast,
        trigger=DateTrigger(run_at),
        kwargs={"message_data": msg_data, "admin_user_id": 1},
        id=job_id,
        jobstore=BROADCAST_JOBSTORE,
        replace_existing=True,
    )

    # Job persisted in Redis store; retrievable
    job = scheduler.get_job(job_id, jobstore=BROADCAST_JOBSTORE)
    assert job is not None
    assert job.id == job_id

    # Cleanup
    scheduler.remove_job(job_id, jobstore=BROADCAST_JOBSTORE)
    assert scheduler.get_job(job_id, jobstore=BROADCAST_JOBSTORE) is None

    await stop_scheduler(scheduler)
    await bot.session.close()


async def test_subscriber_state_enum_matches():
    """Library SubscriberState values must match our DB string literals."""
    from bot.models import BroadcastState

    assert BroadcastState.MEMBER.value == SubscriberState.MEMBER.value == "member"
    assert BroadcastState.KICKED.value == SubscriberState.KICKED.value == "kicked"


async def test_redis_fsm_storage_url():
    """Sanity: RedisStorage.from_url accepts the configured DSN."""
    storage = RedisStorage.from_url(settings.REDIS_DSN)
    assert storage is not None
    await storage.close()
