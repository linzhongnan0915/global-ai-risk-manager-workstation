"""Bearer-token auth for external scheduled refresh calls."""

from __future__ import annotations

import os

EXTERNAL_REFRESH_INTERVAL_MINUTES = 10


def refresh_api_token_configured() -> bool:
    return bool(os.environ.get("REFRESH_API_TOKEN", "").strip())


def parse_bearer_token(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    value = authorization_header.strip()
    if not value.lower().startswith("bearer"):
        return None
    parts = value.split(None, 1)
    if len(parts) < 2:
        return None
    token = parts[1].strip()
    return token if token else None


def bearer_auth_present(authorization_header: str | None) -> bool:
    if not authorization_header:
        return False
    return authorization_header.strip().lower().startswith("bearer")


def classify_refresh_request(authorization_header: str | None) -> tuple[str, bool]:
    """Classify refresh caller.

    Returns
    -------
    (mode, authorized)
        mode: ``external`` | ``manual`` | ``rejected``
    """
    expected = os.environ.get("REFRESH_API_TOKEN", "").strip()
    if bearer_auth_present(authorization_header):
        token = parse_bearer_token(authorization_header)
        if not expected or not token or token != expected:
            return "rejected", False
        return "external", True
    return "manual", True
