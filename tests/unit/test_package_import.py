"""Smoke unit test for package import and version verification."""

import routeforge


def test_package_version() -> None:
    """Verify that routeforge package imports correctly and exposes expected version."""
    assert routeforge.__version__ == "0.1.0"
