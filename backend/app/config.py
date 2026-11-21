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
    # Key the live map page loads in the browser (Maps JavaScript + Places API).
    # Falls back to google_api_key when GOOGLE_MAPS_BROWSER_KEY is blank.
    google_browser_key: str | None = None
    cors_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    route_mode: str = "auto"  # "auto" or "offline"
    # Google sign-in (OAuth) for the person's Gmail / Calendar / Contacts.
    google_oauth_client_file: Path | None = None   # JSON downloaded from Google Cloud
    google_oauth_redirect_uri: str = "http://localhost:8000/api/google/callback"
    # Where the browser lands after "Connect Google" finishes ("" = a simple "connected" page).
    google_oauth_done_url: str = ""
    # Supabase (server-side only). Without both, data lives in memory.
    supabase_url: str | None = None
    supabase_key: str | None = None
    # Fernet key that encrypts the Google refresh token before it is stored.
    token_encryption_key: str | None = None

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_api_key) and self.route_mode != "offline"

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(BACKEND_DIR / ".env")
        key = (os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
        if not key or key.lower().startswith(("your", "paste", "changeme")):
            key = ""
        browser_key = (os.getenv("GOOGLE_MAPS_BROWSER_KEY") or "").strip() or key
        origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        return cls(
            google_api_key=key or None,
            google_browser_key=browser_key or None,
            cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
            route_mode=(os.getenv("ROUTE_MODE") or "auto").strip().lower(),
            google_oauth_client_file=_path(os.getenv("GOOGLE_OAUTH_CLIENT_FILE")),
            google_oauth_redirect_uri=(os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
                                       or "http://localhost:8000/api/google/callback").strip(),
            google_oauth_done_url=(os.getenv("GOOGLE_OAUTH_DONE_URL") or "").strip(),
            supabase_url=(os.getenv("SUPABASE_URL") or "").strip() or None,
            supabase_key=(os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip() or None,
            token_encryption_key=(os.getenv("TOKEN_ENCRYPTION_KEY") or "").strip() or None,
        )


def _path(value: str | None) -> Path | None:
    """Relative paths in .env are relative to the backend folder."""
    if not value or not value.strip():
        return None
    p = Path(value.strip()).expanduser()
    return p if p.is_absolute() else BACKEND_DIR / p
