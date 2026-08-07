"""Integration test for /healthz endpoint using TestClient."""

from fastapi.testclient import TestClient

from routeforge import __version__
from routeforge.gateway import create_app


def test_health_endpoint_returns_200_and_payload() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"

        data = response.json()
        assert data == {
            "status": "ok",
            "service": "routeforge-gateway",
            "version": __version__,
        }


def test_health_endpoint_repeated_requests_identical() -> None:
    app = create_app()
    with TestClient(app) as client:
        res1 = client.get("/healthz").json()
        res2 = client.get("/healthz").json()
        assert res1 == res2
