"""SQLAlchemy-backed BaseBroadcastStorage reading subscribers from UserProfile."""

from __future__ import annotations

from collections.abc import AsyncIterator

from aiogram_broadcast.models import Subscriber, SubscriberState
from aiogram_broadcast.storage.base import BaseBroadcastStorage
from sqlalchemy import func, select

from bot.core.db import DatabaseManager
from bot.models import UserProfile


def _user_to_subscriber(user: UserProfile) -> Subscriber:
    state = SubscriberState(user.broadcast_state) if user.broadcast_state else SubscriberState.MEMBER
    return Subscriber(
        id=user.user_id,
        full_name=user.full_name or "",
        username=user.username,
        language_code=user.preferred_language,
        state=state,
        subscribed_at=user.created_at.isoformat() if user.created_at else "",
    )


class SQLAlchemyBroadcastStorage(BaseBroadcastStorage):
    """Read subscribers from UserProfile (Postgres). Only writes broadcast_state."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    async def add_subscriber(self, subscriber: Subscriber) -> None:
        async with self._db.session() as session:
            existing = await session.get(UserProfile, subscriber.id)
            if existing is not None:
                existing.broadcast_state = subscriber.state.value
                if subscriber.full_name:
                    existing.full_name = subscriber.full_name
                if subscriber.username is not None:
                    existing.username = subscriber.username
                if subscriber.language_code is not None and not existing.preferred_language:
                    existing.preferred_language = subscriber.language_code
                return
            session.add(
                UserProfile(
                    user_id=subscriber.id,
                    full_name=subscriber.full_name or None,
                    username=subscriber.username,
                    preferred_language=subscriber.language_code,
                    broadcast_state=subscriber.state.value,
                )
            )

    async def get_subscriber(self, user_id: int) -> Subscriber | None:
        async with self._db.session() as session:
            user = await session.get(UserProfile, user_id)
            return _user_to_subscriber(user) if user else None

    async def update_subscriber(self, subscriber: Subscriber) -> None:
        async with self._db.session() as session:
            user = await session.get(UserProfile, subscriber.id)
            if user is None:
                return
            user.broadcast_state = subscriber.state.value
            if subscriber.full_name:
                user.full_name = subscriber.full_name
            if subscriber.username is not None:
                user.username = subscriber.username
            if subscriber.language_code is not None:
                user.preferred_language = subscriber.language_code

    async def delete_subscriber(self, user_id: int) -> bool:
        async with self._db.session() as session:
            user = await session.get(UserProfile, user_id)
            if user is None:
                return False
            await session.delete(user)
            return True

    async def get_all_subscriber_ids(
        self,
        state: SubscriberState | None = None,
    ) -> list[int]:
        stmt = select(UserProfile.user_id)
        if state is not None:
            stmt = stmt.where(UserProfile.broadcast_state == state.value)
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]

    async def get_subscribers_count(
        self,
        state: SubscriberState | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(UserProfile)
        if state is not None:
            stmt = stmt.where(UserProfile.broadcast_state == state.value)
        async with self._db.session() as session:
            result = await session.execute(stmt)
            return int(result.scalar_one())

    async def iter_subscribers(
        self,
        state: SubscriberState | None = None,
        batch_size: int = 100,
    ) -> AsyncIterator[Subscriber]:
        stmt = select(UserProfile).order_by(UserProfile.user_id).execution_options(
            yield_per=batch_size
        )
        if state is not None:
            stmt = stmt.where(UserProfile.broadcast_state == state.value)
        async with self._db.session() as session:
            result = await session.stream_scalars(stmt)
            async for user in result:
                yield _user_to_subscriber(user)

    async def update_subscriber_state(
        self,
        user_id: int,
        state: SubscriberState,
    ) -> bool:
        async with self._db.session() as session:
            user = await session.get(UserProfile, user_id)
            if user is None:
                return False
            user.broadcast_state = state.value
            return True
