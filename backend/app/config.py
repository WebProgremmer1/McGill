"""Settings loaded from environment variables / the local .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    google_api_key: str | None = None
    # Separate, website-restricted key for the browser (Maps JavaScript + Places API).
    # It never falls back to google_api_key, which must stay on the server.
    google_browser_key: str | None = None
    cors_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    route_mode: str = "auto"  # "auto" or "offline"

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_api_key) and self.route_mode != "offline"

    @property
    def public_browser_key(self) -> str | None:
        """The only key that may reach a browser."""
        if not self.google_browser_key or self.google_browser_key == self.google_api_key:
            return None
        return self.google_browser_key

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(BACKEND_DIR / ".env")
        key = (os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
        if not key or key.lower().startswith(("your", "paste", "changeme")):
            key = ""
        browser_key = (os.getenv("GOOGLE_MAPS_BROWSER_KEY") or "").strip()
        if browser_key.lower().startswith(("your", "paste", "changeme")):
            browser_key = ""
        origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        return cls(
            google_api_key=key or None,
            google_browser_key=browser_key or None,
            cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
            route_mode=(os.getenv("ROUTE_MODE") or "auto").strip().lower(),
        )
