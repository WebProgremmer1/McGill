"""Storage for data that must survive a restart: the connected Google account and
trusted contacts (escalation tables come next).

Two interchangeable stores with the same methods:
- SupabaseStore: the real database (used when SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY are set).
- MemoryStore:   a dict-backed stand-in for tests and offline demos.

Rows are plain dicts with the same column names as the SQL tables in
supabase/migrations/. Use `create_store(settings)` to get the right one, and
`get_supabase(settings)` if you need the raw Supabase client for something new.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from .config import Settings
from .errors import ApiError, not_found

Row = dict[str, Any]
DEFAULT_PERSON = "default"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def priority_taken(priority: int) -> ApiError:
    return ApiError(409, "priority_taken", f"Another contact already has priority {priority}.")


def email_taken(email: str) -> ApiError:
    return ApiError(409, "email_taken", f"A contact with email {email} already exists.")


class Store(Protocol):
    kind: str

    def ping(self) -> bool: ...
    # google_accounts
    def get_google_account(self, person_key: str = DEFAULT_PERSON) -> Row | None: ...
    def save_google_account(self, row: Row) -> Row: ...
    def delete_google_account(self, person_key: str = DEFAULT_PERSON) -> None: ...
    # contacts
    def list_contacts(self, person_key: str = DEFAULT_PERSON) -> list[Row]: ...
    def get_contact(self, contact_id: str) -> Row: ...
    def create_contact(self, row: Row) -> Row: ...
    def update_contact(self, contact_id: str, fields: Row) -> Row: ...
    def delete_contact(self, contact_id: str) -> None: ...
    def reorder_contacts(self, ordered_ids: list[str], person_key: str = DEFAULT_PERSON) -> list[Row]: ...


# ---------------------------------------------------------------- memory
class MemoryStore:
    kind = "memory"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.google_accounts: dict[str, Row] = {}
        self.contacts: dict[str, Row] = {}

    def ping(self) -> bool:
        return True

    def get_google_account(self, person_key: str = DEFAULT_PERSON) -> Row | None:
        row = self.google_accounts.get(person_key)
        return dict(row) if row else None

    def save_google_account(self, row: Row) -> Row:
        with self._lock:
            key = row.get("person_key", DEFAULT_PERSON)
            old = self.google_accounts.get(key, {})
            new = {"id": old.get("id", str(uuid.uuid4())), "connected_at": _now(),
                   "status": "connected", "person_name": None, "scopes": [],
                   **old, **row, "person_key": key, "updated_at": _now()}
            self.google_accounts[key] = new
            return dict(new)

    def delete_google_account(self, person_key: str = DEFAULT_PERSON) -> None:
        self.google_accounts.pop(person_key, None)

    def list_contacts(self, person_key: str = DEFAULT_PERSON) -> list[Row]:
        rows = [dict(c) for c in self.contacts.values() if c["person_key"] == person_key]
        return sorted(rows, key=lambda c: c["priority"])

    def get_contact(self, contact_id: str) -> Row:
        row = self.contacts.get(contact_id)
        if not row:
            raise not_found("contact", contact_id)
        return dict(row)

    def _check_unique(self, row: Row, skip_id: str | None = None) -> None:
        for c in self.contacts.values():
            if c["id"] == skip_id or c["person_key"] != row["person_key"]:
                continue
            if c["priority"] == row["priority"]:
                raise priority_taken(row["priority"])
            if c["email"].lower() == row["email"].lower():
                raise email_taken(row["email"])

    def create_contact(self, row: Row) -> Row:
        with self._lock:
            new = {"relationship": None, "photo_url": None, "source": "manual",
                   "person_key": DEFAULT_PERSON, **row,
                   "id": str(uuid.uuid4()), "created_at": _now(), "updated_at": _now()}
            self._check_unique(new)
            self.contacts[new["id"]] = new
            return dict(new)

    def update_contact(self, contact_id: str, fields: Row) -> Row:
        with self._lock:
            new = {**self.get_contact(contact_id), **fields, "updated_at": _now()}
            self._check_unique(new, skip_id=contact_id)
            self.contacts[contact_id] = new
            return dict(new)

    def delete_contact(self, contact_id: str) -> None:
        with self._lock:
            self.get_contact(contact_id)
            del self.contacts[contact_id]

    def reorder_contacts(self, ordered_ids: list[str], person_key: str = DEFAULT_PERSON) -> list[Row]:
        with self._lock:
            _check_reorder(self.list_contacts(person_key), ordered_ids)
            for i, cid in enumerate(ordered_ids, start=1):
                self.contacts[cid]["priority"] = i
                self.contacts[cid]["updated_at"] = _now()
            return self.list_contacts(person_key)


def _check_reorder(current: list[Row], ordered_ids: list[str]) -> None:
    if sorted(ordered_ids) != sorted(c["id"] for c in current):
        raise ApiError(422, "invalid_order",
                       "Send every contact id exactly once, in the new order.")


# ---------------------------------------------------------------- supabase
class SupabaseStore:
    kind = "supabase"

    def __init__(self, client: Any) -> None:
        self.db = client

    def ping(self) -> bool:
        try:
            self.db.table("contacts").select("id").limit(1).execute()
            return True
        except Exception:  # noqa: BLE001 - health check only
            return False

    @staticmethod
    def _raise_db(e: Exception, row: Row | None = None) -> None:
        """Turn Postgres unique violations into the same 409s MemoryStore raises."""
        code = getattr(e, "code", None)
        text = str(getattr(e, "message", "") or e)
        if code == "23505" and row is not None:
            if "priority" in text:
                raise priority_taken(row.get("priority"))
            if "email" in text:
                raise email_taken(row.get("email"))
        if code == "PGRST205":
            raise ApiError(503, "database_not_set_up",
                           "Supabase tables are missing. Run supabase/migrations/*.sql in the SQL Editor.")
        raise e

    def get_google_account(self, person_key: str = DEFAULT_PERSON) -> Row | None:
        try:
            res = self.db.table("google_accounts").select("*").eq("person_key", person_key).limit(1).execute()
        except Exception as e:  # noqa: BLE001
            self._raise_db(e)
        return res.data[0] if res.data else None

    def save_google_account(self, row: Row) -> Row:
        row = {"person_key": DEFAULT_PERSON, **row, "status": row.get("status", "connected"),
               "updated_at": _now()}
        try:
            res = self.db.table("google_accounts").upsert(row, on_conflict="person_key").execute()
        except Exception as e:  # noqa: BLE001
            self._raise_db(e)
        return res.data[0]

    def delete_google_account(self, person_key: str = DEFAULT_PERSON) -> None:
        self.db.table("google_accounts").delete().eq("person_key", person_key).execute()

    def list_contacts(self, person_key: str = DEFAULT_PERSON) -> list[Row]:
        try:
            res = (self.db.table("contacts").select("*").eq("person_key", person_key)
                   .order("priority").execute())
        except Exception as e:  # noqa: BLE001
            self._raise_db(e)
        return res.data

    def get_contact(self, contact_id: str) -> Row:
        try:
            uuid.UUID(contact_id)
        except ValueError:
            raise not_found("contact", contact_id) from None
        res = self.db.table("contacts").select("*").eq("id", contact_id).limit(1).execute()
        if not res.data:
            raise not_found("contact", contact_id)
        return res.data[0]

    def create_contact(self, row: Row) -> Row:
        row = {"person_key": DEFAULT_PERSON, **row}
        try:
            res = self.db.table("contacts").insert(row).execute()
        except Exception as e:  # noqa: BLE001
            self._raise_db(e, row)
        return res.data[0]

    def update_contact(self, contact_id: str, fields: Row) -> Row:
        current = self.get_contact(contact_id)
        try:
            res = (self.db.table("contacts").update({**fields, "updated_at": _now()})
                   .eq("id", contact_id).execute())
        except Exception as e:  # noqa: BLE001
            self._raise_db(e, {**current, **fields})
        return res.data[0]

    def delete_contact(self, contact_id: str) -> None:
        self.get_contact(contact_id)
        self.db.table("contacts").delete().eq("id", contact_id).execute()

    def reorder_contacts(self, ordered_ids: list[str], person_key: str = DEFAULT_PERSON) -> list[Row]:
        current = self.list_contacts(person_key)
        _check_reorder(current, ordered_ids)
        # (person_key, priority) is unique, so park everyone on free numbers first.
        offset = max([c["priority"] for c in current] + [0]) + len(current) + 1
        for i, cid in enumerate(ordered_ids):
            self.db.table("contacts").update({"priority": offset + i}).eq("id", cid).execute()
        for i, cid in enumerate(ordered_ids, start=1):
            self.db.table("contacts").update({"priority": i, "updated_at": _now()}).eq("id", cid).execute()
        return self.list_contacts(person_key)


# ---------------------------------------------------------------- factory
def get_supabase(settings: Settings) -> Any:
    """Raw Supabase client (server-side secret key). Never send this key to a browser."""
    if not settings.supabase_enabled:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env")
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_key)


def create_store(settings: Settings) -> Store:
    return SupabaseStore(get_supabase(settings)) if settings.supabase_enabled else MemoryStore()
