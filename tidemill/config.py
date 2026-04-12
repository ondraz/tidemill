"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os


class AuthConfig:
    """Authentication configuration (Clerk + API keys)."""

    auth_enabled: bool = os.environ.get("AUTH_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
    )
    clerk_secret_key: str = os.environ.get("CLERK_SECRET_KEY", "")
    clerk_publishable_key: str = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
    clerk_jwks_url: str = os.environ.get(
        "CLERK_JWKS_URL",
        "",
    )
    cors_origins: list[str] = [
        o.strip()
        for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
        if o.strip()
    ]

    @property
    def clerk_enabled(self) -> bool:
        return bool(self.clerk_secret_key)
