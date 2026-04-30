from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from bot.config.settings import settings
from bot.core.logger import get_logger

logger = get_logger(__name__)

Base = declarative_base()


class DatabaseManager:
    """Manages PostgreSQL connections and sessions."""

    def __init__(self) -> None:
        """Initialize database manager."""
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def connect(self) -> None:
        """Establish database connection."""
        try:
            self._engine = create_async_engine(
                settings.POSTGRES_DSN,
                echo=settings.LOG_LEVEL == "DEBUG",
                pool_size=20,
                max_overflow=10,
                pool_pre_ping=True,
            )

            self._session_factory = async_sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            async with self._engine.begin() as conn:
                await conn.execute(text("SELECT 1"))

            logger.info("database_connected", dsn=settings.POSTGRES_DSN.split("@")[-1])

        except Exception as e:
            logger.error("database_connection_failed", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Close database connection."""
        if self._engine:
            await self._engine.dispose()
            logger.info("database_disconnected")

    async def health_check(self) -> bool:
        """Check database connection health."""
        try:
            if self._engine:
                async with self._engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                return True
            return False
        except Exception:
            return False

    @property
    def engine(self) -> AsyncEngine:
        """Get SQLAlchemy engine."""
        if not self._engine:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Get database session context manager."""
        if not self._session_factory:
            raise RuntimeError("Database not connected. Call connect() first.")

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


db_manager = DatabaseManager()
