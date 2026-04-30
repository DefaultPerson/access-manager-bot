"""Integration test for SQLAlchemyBroadcastStorage.

Requires: live Postgres at the DSN configured in .env (or env vars). The fixture
creates and rolls back its own UserProfile rows.
"""

from __future__ import annotations

import uuid

import pytest
from aiogram_broadcast.models import Subscriber, SubscriberState
from sqlalchemy import delete

from bot.core.db import db_manager
from bot.models import UserProfile
from bot.services.broadcast_storage import SQLAlchemyBroadcastStorage


@pytest.fixture(scope="module", autouse=True)
async def setup_db():
    await db_manager.connect()
    yield
    await db_manager.disconnect()


@pytest.fixture
async def storage():
    return SQLAlchemyBroadcastStorage(db_manager)


@pytest.fixture
async def fake_users():
    """Insert 3 fake users; clean up after the test."""
    base_id = 9_000_000_000 + (uuid.uuid4().int % 1_000_000)
    ids = [base_id + i for i in range(3)]
    async with db_manager.session() as session:
        for i, uid in enumerate(ids):
            session.add(
                UserProfile(
                    user_id=uid,
                    username=f"user_{i}",
                    full_name=f"Test User {i}",
                    preferred_language="en",
                    broadcast_state="member",
                )
            )
    yield ids
    async with db_manager.session() as session:
        await session.execute(delete(UserProfile).where(UserProfile.user_id.in_(ids)))


async def test_get_subscriber(storage: SQLAlchemyBroadcastStorage, fake_users: list[int]):
    sub = await storage.get_subscriber(fake_users[0])
    assert sub is not None
    assert sub.id == fake_users[0]
    assert sub.full_name == "Test User 0"
    assert sub.username == "user_0"
    assert sub.language_code == "en"
    assert sub.state == SubscriberState.MEMBER


async def test_get_subscriber_missing(storage: SQLAlchemyBroadcastStorage):
    sub = await storage.get_subscriber(123_456_789_000)
    assert sub is None


async def test_get_all_subscriber_ids_active(
    storage: SQLAlchemyBroadcastStorage, fake_users: list[int]
):
    ids = await storage.get_all_subscriber_ids(state=SubscriberState.MEMBER)
    for uid in fake_users:
        assert uid in ids


async def test_get_subscribers_count(
    storage: SQLAlchemyBroadcastStorage, fake_users: list[int]
):
    total_active = await storage.get_subscribers_count(state=SubscriberState.MEMBER)
    assert total_active >= 3


async def test_iter_subscribers(
    storage: SQLAlchemyBroadcastStorage, fake_users: list[int]
):
    seen_ids: list[int] = []
    async for sub in storage.iter_subscribers(state=SubscriberState.MEMBER):
        if sub.id in fake_users:
            seen_ids.append(sub.id)
    assert sorted(seen_ids) == sorted(fake_users)


async def test_update_subscriber_state(
    storage: SQLAlchemyBroadcastStorage, fake_users: list[int]
):
    uid = fake_users[1]
    ok = await storage.update_subscriber_state(uid, SubscriberState.KICKED)
    assert ok is True
    sub = await storage.get_subscriber(uid)
    assert sub is not None
    assert sub.state == SubscriberState.KICKED

    # KICKED users excluded from active filter
    active_ids = await storage.get_all_subscriber_ids(state=SubscriberState.MEMBER)
    assert uid not in active_ids
    kicked_ids = await storage.get_all_subscriber_ids(state=SubscriberState.KICKED)
    assert uid in kicked_ids


async def test_update_subscriber(
    storage: SQLAlchemyBroadcastStorage, fake_users: list[int]
):
    uid = fake_users[2]
    sub = Subscriber(
        id=uid,
        full_name="Renamed User",
        username="renamed",
        language_code="ru",
        state=SubscriberState.MEMBER,
    )
    await storage.update_subscriber(sub)

    refreshed = await storage.get_subscriber(uid)
    assert refreshed is not None
    assert refreshed.full_name == "Renamed User"
    assert refreshed.username == "renamed"
    assert refreshed.language_code == "ru"


async def test_add_subscriber_existing_does_not_raise(
    storage: SQLAlchemyBroadcastStorage, fake_users: list[int]
):
    """add_subscriber should be idempotent on existing users."""
    sub = Subscriber(
        id=fake_users[0],
        full_name="Test User 0",
        username="user_0",
        language_code="en",
        state=SubscriberState.MEMBER,
    )
    await storage.add_subscriber(sub)
    refreshed = await storage.get_subscriber(fake_users[0])
    assert refreshed is not None
    assert refreshed.full_name == "Test User 0"
