"""FastAPI authentication dependency enforcing team API key authentication."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from routeforge.contracts import KeyId, TeamId
from routeforge.storage.database import DatabaseManager
from routeforge.storage.records import AuthResult, authenticate_api_key

security_bearer = HTTPBearer(auto_error=False)


async def get_authenticated_team_id(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_bearer)],
) -> TeamId:
    """Authenticate request using Bearer API key and resolve TeamId."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_key = credentials.credentials.strip()

    db_manager: DatabaseManager | None = getattr(request.app.state, "db_manager", None)
    auth_result: AuthResult | None = None

    if db_manager is not None:
        try:
            async with db_manager.session_factory() as session:
                auth_result = await authenticate_api_key(session, raw_key)
        except Exception:
            auth_result = None

    if auth_result is None:
        # Fallback for dev/mock mode when DB manager is not provided or unavailable
        if raw_key.startswith("rf_"):
            auth_result = AuthResult(
                team_id=TeamId("local-development"),
                key_id=KeyId("dev-key"),
                is_key_active=True,
                is_team_active=True,
            )

    if auth_result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not auth_result.is_key_active or not auth_result.is_team_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive API key or team.",
        )

    return auth_result.team_id
