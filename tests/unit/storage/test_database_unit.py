"""Unit tests for DatabaseManager and database connection helper."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routeforge.storage.database import DatabaseManager, get_database_url


def test_get_database_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUTEFORGE_DATABASE_URL", "postgresql+asyncpg://user:pass@host:5432/db")
    assert get_database_url() == "postgresql+asyncpg://user:pass@host:5432/db"


@pytest.mark.anyio
async def test_database_manager_aclose_and_session() -> None:
    with patch("routeforge.storage.database.create_async_engine") as mock_create_engine:
        mock_engine = AsyncMock()
        mock_create_engine.return_value = mock_engine

        mgr = DatabaseManager("postgresql+asyncpg://user:pass@localhost:5432/db")

        mock_session = AsyncMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None

        mgr.session_factory = MagicMock(return_value=mock_cm)

        sessions = []
        async for sess in mgr.get_session():
            sessions.append(sess)

        assert len(sessions) == 1
        assert sessions[0] is mock_session

        await mgr.aclose()
        mock_engine.dispose.assert_awaited_once()
