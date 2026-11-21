"""No-signal watchdog and live Server-Sent Events."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.events import EventBus, format_sse, sse_stream
from app.main import create_app

from conftest import HOME, make_journey, send


def later(minutes):
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def service_of(client):
    return client.app.state.service


def event_types(client, journey_id=None):
    return [e["type"] for e in service_of(client).events.recent(200)
            if journey_id is None or e["journey_id"] == journey_id]


# ---------------------------------------------------------------- no-signal watchdog
def test_no_signal_alert_after_five_silent_minutes(client, journey):
    svc = service_of(client)
    send(client, journey["id"], *HOME, 0)
    assert svc.check_silence(later(4.5)) == []            # quiet, but not for long enough
    raised = svc.check_silence(later(6))
    assert len(raised) == 1
    alert = client.get("/api/alerts", params={"journey_id": journey["id"]}).json()[0]
    assert alert["type"] == "no_signal" and alert["priority"] == "high"
    assert "No location from Margaret" in alert["message"] and "Last known position" in alert["message"]
    assert alert["resolved_at"] is None
    assert svc.check_silence(later(9)) == []                # one alert per silence
    assert "alert_created" in event_types(client, journey["id"])


def test_gps_coming_back_resolves_the_alert_and_rearms_it(client, journey):
    svc = service_of(client)
    svc.check_silence(later(6))                             # silent from the very start
    alert = client.get("/api/alerts").json()[0]
    assert "No position was ever received" in alert["message"]
    send(client, journey["id"], *HOME, 0)                   # phone is back
    alert = client.get(f"/api/alerts").json()[0]
    assert alert["resolved_at"] is not None and alert["acknowledged"] is False
    assert "alert_resolved" in event_types(client, journey["id"])
    assert len(svc.check_silence(later(12))) == 1           # a new silence = a new alert
    assert len(client.get("/api/alerts").json()) == 2


def test_acknowledged_no_signal_alert_is_not_repeated_but_next_silence_is(client, journey):
    svc = service_of(client)
    svc.check_silence(later(6))
    alert_id = client.get("/api/alerts").json()[0]["id"]
    client.post(f"/api/alerts/{alert_id}/acknowledge")
    assert len(svc.check_silence(later(7))) == 1            # acked != fixed; still silent
    assert "alert_acknowledged" in event_types(client)


def test_watchdog_skips_ended_and_unwatched_journeys(client):
    svc = service_of(client)
    done = make_journey(client)
    client.post(f"/api/journeys/{done['id']}/complete")
    make_journey(client, signal_watch=False)
    demo = client.post("/api/demo/run").json()
    assert svc.check_silence(later(60)) == []
    assert client.get(f"/api/journeys/{demo['journey_id']}").json()["signal_watch"] is False


def test_ending_a_journey_resolves_its_no_signal_alert(client, journey):
    service_of(client).check_silence(later(6))
    client.post(f"/api/journeys/{journey['id']}/cancel")
    assert client.get("/api/alerts").json()[0]["resolved_at"] is not None
    assert event_types(client, journey["id"])[-2:] == ["alert_resolved", "journey_ended"]


def test_background_watchdog_runs_inside_the_server():
    settings = Settings(route_mode="offline", no_signal_after_s=0.2, watchdog_interval_s=0.05)
    with TestClient(create_app(settings)) as c:            # `with` starts the lifespan task
        j = make_journey(c)
        deadline = time.time() + 3
        while time.time() < deadline and not c.get("/api/alerts").json():
            time.sleep(0.05)
        alerts = c.get("/api/alerts").json()
    assert [a["type"] for a in alerts] == ["no_signal"] and alerts[0]["journey_id"] == j["id"]


# ---------------------------------------------------------------- events from normal use
def test_actions_publish_events(client, journey):
    jid = journey["id"]
    send(client, jid, *HOME, 0)
    client.post(f"/api/journeys/{jid}/checkin", json={"help_requested": True})
    alert_id = client.get("/api/alerts").json()[0]["id"]
    client.post(f"/api/alerts/{alert_id}/acknowledge")
    client.post(f"/api/journeys/{jid}/complete")
    assert event_types(client, jid) == ["risk_updated", "alert_created", "alert_acknowledged", "journey_ended"]
    risk_event = service_of(client).events.recent(10)[0]
    assert risk_event["data"]["risk"]["score"] == 0 and risk_event["data"]["location"]["latitude"] == HOME[0]


def test_unknown_event_type_is_rejected(client):
    r = client.get("/api/events", params={"types": "alert_created,nope"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_event_type"


# ---------------------------------------------------------------- event bus + SSE stream
def run(coro):
    return asyncio.run(coro)


def test_bus_filters_by_journey_and_type_and_replays_missed_events():
    async def scenario():
        bus = EventBus()
        bus.publish("risk_updated", "j1", {"n": 1})
        first = bus.publish("alert_created", "j1", {"n": 2})
        mine = bus.subscribe(journey_id="j1")
        alerts_only = bus.subscribe(types=frozenset({"alert_created"}))
        resumed = bus.subscribe(last_event_id=first["id"] - 1)   # reconnecting browser
        bus.publish("risk_updated", "j2", {"n": 3})
        bus.publish("alert_created", "j1", {"n": 4})
        await asyncio.sleep(0)                                    # let call_soon_threadsafe run
        drain = lambda s: [s.queue.get_nowait()["data"]["n"] for _ in range(s.queue.qsize())]
        return drain(mine), drain(alerts_only), drain(resumed), bus

    mine, alerts_only, resumed, bus = run(scenario())
    assert mine == [4] and alerts_only == [4] and resumed == [2, 3, 4]
    assert bus.subscriber_count == 3


def test_slow_subscriber_keeps_the_newest_events():
    async def scenario():
        bus = EventBus()
        sub = bus.subscribe()
        for n in range(250):
            bus.publish("risk_updated", "j", {"n": n})
        await asyncio.sleep(0)
        return [sub.queue.get_nowait()["data"]["n"] for _ in range(sub.queue.qsize())]

    got = run(scenario())
    assert len(got) == 200 and got[0] == 50 and got[-1] == 249


def test_sse_stream_sends_events_heartbeats_and_cleans_up():
    async def scenario():
        bus = EventBus()
        gone = False

        async def is_disconnected():
            return gone

        stream = sse_stream(bus, is_disconnected, heartbeat_s=0.05)
        chunks = [await stream.__anext__()]                       # "connected" preamble
        bus.publish("alert_created", "j1", {"message": "hi"})
        chunks.append(await stream.__anext__())
        chunks.append(await stream.__anext__())                   # idle -> keep-alive
        gone = True
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()
        return chunks, bus.subscriber_count

    chunks, subs = run(scenario())
    assert chunks[0].startswith("retry: 3000")
    head, data = chunks[1].strip().split("\ndata: ")
    assert head == "id: 1\nevent: alert_created"
    assert json.loads(data)["data"] == {"message": "hi"}
    assert chunks[2] == ": keep-alive\n\n"
    assert subs == 0


def test_format_sse_is_one_event_per_blank_line():
    text = format_sse({"id": 7, "type": "alert_created", "journey_id": None, "sent_at": "x",
                       "data": {"m": "line1\nline2"}})
    assert text.endswith("\n\n") and text.count("\n\n") == 1      # newline in data stays escaped
