"""Runs against the REAL Supabase project in backend/.env. Skipped unless asked:

    RUN_SUPABASE_TESTS=1 python -m pytest tests/test_supabase_live.py -q

Uses its own person_key and deletes everything it creates.
"""
import os
import uuid

import pytest

from app.config import Settings
from app.db import SupabaseStore, get_supabase
from app.errors import ApiError

pytestmark = pytest.mark.skipif(os.getenv("RUN_SUPABASE_TESTS") != "1",
                                reason="set RUN_SUPABASE_TESTS=1 to hit the real Supabase project")


@pytest.fixture
def live():
    settings = Settings.from_env()
    if not settings.supabase_enabled:
        pytest.skip("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set")
    client = get_supabase(settings)
    store = SupabaseStore(client)
    key = f"pytest-{uuid.uuid4().hex[:8]}"
    yield store, key
    client.table("contacts").delete().eq("person_key", key).execute()
    client.table("google_accounts").delete().eq("person_key", key).execute()


def test_tables_exist(live):
    store, _ = live
    assert store.ping()


def test_contacts_roundtrip(live):
    store, key = live
    a = store.create_contact({"person_key": key, "name": "Anna", "email": "anna@example.com", "priority": 1})
    b = store.create_contact({"person_key": key, "name": "Ben", "email": "ben@example.com", "priority": 2,
                              "relationship": "son"})
    assert [c["name"] for c in store.list_contacts(key)] == ["Anna", "Ben"]

    with pytest.raises(ApiError) as e:
        store.create_contact({"person_key": key, "name": "X", "email": "x@example.com", "priority": 1})
    assert e.value.code == "priority_taken"
    with pytest.raises(ApiError) as e:
        store.create_contact({"person_key": key, "name": "X", "email": "anna@example.com", "priority": 3})
    assert e.value.code == "email_taken"

    assert store.update_contact(b["id"], {"relationship": "grandson"})["relationship"] == "grandson"
    order = store.reorder_contacts([b["id"], a["id"]], key)
    assert [(c["name"], c["priority"]) for c in order] == [("Ben", 1), ("Anna", 2)]

    store.delete_contact(a["id"])
    with pytest.raises(ApiError):
        store.get_contact(a["id"])
    with pytest.raises(ApiError):
        store.get_contact("not-a-uuid")


def test_google_account_upsert(live):
    store, key = live
    store.save_google_account({"person_key": key, "google_email": "m@example.com",
                               "refresh_token_enc": "enc-1", "scopes": ["openid"]})
    store.save_google_account({"person_key": key, "google_email": "m@example.com",
                               "refresh_token_enc": "enc-2", "scopes": ["openid", "email"]})
    row = store.get_google_account(key)
    assert row["refresh_token_enc"] == "enc-2" and row["scopes"] == ["openid", "email"]
    store.delete_google_account(key)
    assert store.get_google_account(key) is None
