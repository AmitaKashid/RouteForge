"""PostgreSQL async engine and session factory lifecycle management."""

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://routeforge:routeforge_pass@localhost:5432/routeforge_dev"
)


def get_database_url() -> str:
    """Retrieve database connection URL from environment or default."""
    return os.getenv("ROUTEFORGE_DATABASE_URL", DEFAULT_DATABASE_URL)


class DatabaseManager:
    """Manages SQLAlchemy async engine lifecycle and session factory."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or get_database_url()
        self.engine: AsyncEngine = create_async_engine(
            self.database_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide an async session generator for request handlers."""
        async with self.session_factory() as session:
            yield session

    async def aclose(self) -> None:
        """Dispose database engine connections gracefully."""
        await self.engine.dispose()
