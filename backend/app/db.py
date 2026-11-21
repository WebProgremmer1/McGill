"""Storage for data that must survive a restart: the connected Google account,
trusted contacts, and email escalations (with every email sent).

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
    # escalations + notifications_sent
    def create_escalation(self, row: Row) -> Row: ...
    def get_escalation(self, escalation_id: str) -> Row: ...
    def update_escalation(self, escalation_id: str, fields: Row) -> Row: ...
    def list_escalations(self, status: str | None = None, journey_id: str | None = None) -> list[Row]: ...
    def claim_notification(self, row: Row) -> Row | None: ...
    def update_notification(self, notification_id: str, fields: Row) -> None: ...
    def list_notifications(self, escalation_id: str) -> list[Row]: ...
    def find_notification_by_token(self, token_hash: str) -> Row | None: ...


# ---------------------------------------------------------------- memory
class MemoryStore:
    kind = "memory"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.google_accounts: dict[str, Row] = {}
        self.contacts: dict[str, Row] = {}
        self.escalations: dict[str, Row] = {}
        self.notifications: dict[str, Row] = {}

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

    # ---------------------------------------------------------- escalations
    def create_escalation(self, row: Row) -> Row:
        with self._lock:
            new = {"person_key": DEFAULT_PERSON, "status": "open", "next_priority": None,
                   "next_step_at": None, "snapshot": {}, "acknowledged_by": None,
                   "closed_at": None, **row, "id": str(uuid.uuid4()), "opened_at": _now()}
            self.escalations[new["id"]] = new
            return dict(new)

    def get_escalation(self, escalation_id: str) -> Row:
        row = self.escalations.get(escalation_id)
        if not row:
            raise not_found("escalation", escalation_id)
        return dict(row)

    def update_escalation(self, escalation_id: str, fields: Row) -> Row:
        with self._lock:
            new = {**self.get_escalation(escalation_id), **fields}
            self.escalations[escalation_id] = new
            return dict(new)

    def list_escalations(self, status: str | None = None, journey_id: str | None = None) -> list[Row]:
        rows = [dict(e) for e in self.escalations.values()
                if (status is None or e["status"] == status)
                and (journey_id is None or e["journey_id"] == journey_id)]
        return sorted(rows, key=lambda e: e["opened_at"], reverse=True)

    def claim_notification(self, row: Row) -> Row | None:
        with self._lock:
            for n in self.notifications.values():
                if (n["escalation_id"], n["kind"], n["recipient"]) == (
                        row["escalation_id"], row["kind"], row["recipient"]):
                    return None
            new = {"ack_token_hash": None, "gmail_message_id": None, "error": None,
                   **row, "id": str(uuid.uuid4()), "sent_at": _now()}
            self.notifications[new["id"]] = new
            return dict(new)

    def update_notification(self, notification_id: str, fields: Row) -> None:
        with self._lock:
            self.notifications[notification_id].update(fields)

    def list_notifications(self, escalation_id: str) -> list[Row]:
        rows = [dict(n) for n in self.notifications.values() if n["escalation_id"] == escalation_id]
        return sorted(rows, key=lambda n: n["sent_at"])

    def find_notification_by_token(self, token_hash: str) -> Row | None:
        return next((dict(n) for n in self.notifications.values()
                     if n["ack_token_hash"] == token_hash), None)


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

    # ---------------------------------------------------------- escalations
    def create_escalation(self, row: Row) -> Row:
        try:
            res = self.db.table("escalations").insert({"person_key": DEFAULT_PERSON, **row}).execute()
        except Exception as e:  # noqa: BLE001
            self._raise_db(e)
        return res.data[0]

    def get_escalation(self, escalation_id: str) -> Row:
        try:
            uuid.UUID(escalation_id)
        except ValueError:
            raise not_found("escalation", escalation_id) from None
        res = self.db.table("escalations").select("*").eq("id", escalation_id).limit(1).execute()
        if not res.data:
            raise not_found("escalation", escalation_id)
        return res.data[0]

    def update_escalation(self, escalation_id: str, fields: Row) -> Row:
        res = self.db.table("escalations").update(fields).eq("id", escalation_id).execute()
        if not res.data:
            raise not_found("escalation", escalation_id)
        return res.data[0]

    def list_escalations(self, status: str | None = None, journey_id: str | None = None) -> list[Row]:
        q = self.db.table("escalations").select("*")
        if status:
            q = q.eq("status", status)
        if journey_id:
            q = q.eq("journey_id", journey_id)
        try:
            return q.order("opened_at", desc=True).limit(200).execute().data
        except Exception as e:  # noqa: BLE001
            self._raise_db(e)

    def claim_notification(self, row: Row) -> Row | None:
        """Insert the row before sending; None if this email was already sent (unique key)."""
        try:
            res = self.db.table("notifications_sent").insert(row).execute()
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", None) == "23505":
                return None
            self._raise_db(e)
        return res.data[0]

    def update_notification(self, notification_id: str, fields: Row) -> None:
        self.db.table("notifications_sent").update(fields).eq("id", notification_id).execute()

    def list_notifications(self, escalation_id: str) -> list[Row]:
        return (self.db.table("notifications_sent").select("*").eq("escalation_id", escalation_id)
                .order("sent_at").execute().data)

    def find_notification_by_token(self, token_hash: str) -> Row | None:
        res = (self.db.table("notifications_sent").select("*").eq("ack_token_hash", token_hash)
               .limit(1).execute())
        return res.data[0] if res.data else None


# ---------------------------------------------------------------- factory
def get_supabase(settings: Settings) -> Any:
    """Raw Supabase client (server-side secret key). Never send this key to a browser."""
    if not settings.supabase_enabled:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env")
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_key)


def create_store(settings: Settings) -> Store:
    return SupabaseStore(get_supabase(settings)) if settings.supabase_enabled else MemoryStore()
