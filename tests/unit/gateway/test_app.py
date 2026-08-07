"""Unit tests for FastAPI application factory (create_app)."""

from fastapi import FastAPI

from routeforge import __version__
from routeforge.gateway import create_app


def test_create_app_factory_returns_new_instance() -> None:
    app1 = create_app()
    app2 = create_app()

    assert isinstance(app1, FastAPI)
    assert isinstance(app2, FastAPI)
    assert app1 is not app2


def test_create_app_metadata_and_urls() -> None:
    app = create_app()

    assert app.title == "RouteForge"
    assert app.version == __version__
    assert app.openapi_url == "/openapi.json"
    assert app.docs_url == "/docs"
    assert app.redoc_url == "/redoc"


def test_create_app_health_route_registered() -> None:
    app = create_app()
    assert app.url_path_for("health_check") == "/healthz"


def test_create_app_with_circuit_breaker_and_state() -> None:
    cb = object()
    app = create_app(circuit_breaker=cb)
    assert app.state.circuit_breaker is cb
