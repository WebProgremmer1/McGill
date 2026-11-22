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
    # The map's From/To search falls back to OpenStreetMap (Photon) when Google Places is not enabled.
    place_search_fallback: bool = True
    # Google sign-in (OAuth) for the person's Gmail and Calendar.
    google_oauth_client_file: Path | None = None   # JSON downloaded from Google Cloud
    google_oauth_redirect_uri: str = "http://localhost:8000/api/google/callback"
    # Where the browser lands after "Connect Google" finishes ("" = a simple "connected" page).
    google_oauth_done_url: str = ""
    # Supabase (server-side only). Without both, data lives in memory.
    supabase_url: str | None = None
    supabase_key: str | None = None
    # Fernet key that encrypts the Google refresh token before it is stored.
    token_encryption_key: str | None = None
    # One approved rehearsal account, caregiver, and calendar. Nothing is emailed without all of them.
    google_allowed_email: str | None = None
    help_email_to: str | None = None
    help_email_consent: bool = False
    google_calendar_id: str | None = None
    # Email escalation (wall-clock seconds; shorten them for a demo).
    public_base_url: str = "http://localhost:8000"   # "I'm on it" links in emails point here
    checkin_reply_timeout_s: int = 180   # medium check-in unanswered this long -> email contact #1
    escalation_step_s: int = 300         # no "I'm on it" this long -> email the next contact
    escalation_tick_s: int = 15          # how often the background timer checks
    # Visit reminders (Google Calendar): shown this long before a visit until this long after it starts.
    visit_reminder_lead_min: int = 20
    visit_reminder_grace_min: int = 30
    # Email Margaret about every timed calendar event, VISIT_REMINDER_LEAD_MIN before it starts.
    calendar_emails: bool = True

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_api_key) and self.route_mode != "offline"

    @property
    def public_browser_key(self) -> str | None:
        """The only key that may reach a browser."""
        if not self.google_browser_key or self.google_browser_key == self.google_api_key:
            return None
        return self.google_browser_key

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

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
            place_search_fallback=(os.getenv("PLACE_SEARCH_FALLBACK") or "on").strip().lower() not in ("off", "no", "false", "0"),
            google_oauth_client_file=_path(os.getenv("GOOGLE_OAUTH_CLIENT_FILE")),
            google_oauth_redirect_uri=(os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
                                       or "http://localhost:8000/api/google/callback").strip(),
            google_oauth_done_url=(os.getenv("GOOGLE_OAUTH_DONE_URL") or "").strip(),
            supabase_url=(os.getenv("SUPABASE_URL") or "").strip() or None,
            supabase_key=(os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip() or None,
            token_encryption_key=(os.getenv("TOKEN_ENCRYPTION_KEY") or "").strip() or None,
            google_allowed_email=(os.getenv("GOOGLE_ALLOWED_ACCOUNT_EMAIL") or "").strip().lower() or None,
            help_email_to=(os.getenv("HELP_EMAIL_TO") or "").strip() or None,
            help_email_consent=(os.getenv("HELP_EMAIL_CONSENT") or "").strip().lower() == "yes",
            google_calendar_id=(os.getenv("GOOGLE_CALENDAR_ID") or "").strip() or None,
            public_base_url=(os.getenv("PUBLIC_BASE_URL") or "http://localhost:8000").strip().rstrip("/"),
            checkin_reply_timeout_s=_int("CHECKIN_REPLY_TIMEOUT_S", 180),
            escalation_step_s=_int("ESCALATION_STEP_S", 300),
            escalation_tick_s=_int("ESCALATION_TICK_S", 15),
            visit_reminder_lead_min=_int("VISIT_REMINDER_LEAD_MIN", 20),
            visit_reminder_grace_min=_int("VISIT_REMINDER_GRACE_MIN", 30),
            calendar_emails=(os.getenv("CALENDAR_EMAILS") or "on").strip().lower() not in ("off", "0", "false", "no"),
        )


def _int(name: str, default: int) -> int:
    value = (os.getenv(name) or "").strip()
    try:
        return max(1, int(value)) if value else default
    except ValueError:
        raise ValueError(f"{name} must be a whole number of seconds, got {value!r}") from None


def _path(value: str | None) -> Path | None:
    """Relative paths in .env are relative to the backend folder."""
    if not value or not value.strip():
        return None
    p = Path(value.strip()).expanduser()
    return p if p.is_absolute() else BACKEND_DIR / p
