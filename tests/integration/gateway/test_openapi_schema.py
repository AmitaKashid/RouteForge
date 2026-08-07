"""Integration test verifying generated OpenAPI documentation schema."""

from fastapi.testclient import TestClient

from routeforge import __version__
from routeforge.gateway import create_app


def test_openapi_schema_endpoint() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200

        schema = response.json()
        assert schema["info"]["title"] == "RouteForge"
        assert schema["info"]["version"] == __version__

        paths = schema["paths"]
        assert "/healthz" in paths
        assert "/v1/chat/completions" in paths
