"""Live events for caregiver dashboards (Server-Sent Events).

The service calls `EventBus.publish(...)` whenever something happens (an alert is
raised, a check-in is created, the risk changes...). Every open
`GET /api/events` connection receives it immediately; no polling needed.

Browsers reconnect automatically and send the id of the last event they saw
(`Last-Event-ID`); we replay what they missed from a small in-memory buffer.

publish() is thread-safe: FastAPI runs our sync endpoints in a thread pool,
while subscribers live on the event loop.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi.encoders import jsonable_encoder

EVENT_TYPES = (
    "risk_updated",        # every GPS update: new score/level/reasons
    "checkin_created",
    "checkin_answered",
    "alert_created",       # risk, help_request or no_signal alert
    "alert_acknowledged",
    "alert_resolved",      # a no_signal alert cleared because GPS came back
    "journey_ended",       # completed or cancelled
)


@dataclass(eq=False)  # compared by identity, so it can live in a set
class Subscriber:
    loop: asyncio.AbstractEventLoop
    journey_id: str | None = None
    types: frozenset[str] | None = None
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=200))

    def wants(self, event: dict) -> bool:
        if self.journey_id and event["journey_id"] != self.journey_id:
            return False
        return self.types is None or event["type"] in self.types

    def put(self, event: dict) -> None:
        """Runs on the subscriber's loop. A slow client loses its oldest events."""
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(event)


class EventBus:
    def __init__(self, history: int = 500):
        self._subs: set[Subscriber] = set()
        self._history: deque[dict] = deque(maxlen=history)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def recent(self, n: int = 50) -> list[dict]:
        """The last `n` events (newest last)."""
        with self._lock:
            return list(self._history)[-n:]

    def publish(self, type_: str, journey_id: str | None, data: Any) -> dict:
        assert type_ in EVENT_TYPES, type_
        with self._lock:
            event = {
                "id": next(self._ids),
                "type": type_,
                "journey_id": journey_id,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "data": jsonable_encoder(data),
            }
            self._history.append(event)
            subs = list(self._subs)
        for sub in subs:
            if sub.wants(event):
                try:
                    sub.loop.call_soon_threadsafe(sub.put, event)
                except RuntimeError:  # its loop has closed: the client is gone
                    self.unsubscribe(sub)
        return event

    def subscribe(self, journey_id: str | None = None, types: frozenset[str] | None = None,
                  last_event_id: int | None = None) -> Subscriber:
        """Must be called from the event loop the subscriber will read on."""
        sub = Subscriber(asyncio.get_running_loop(), journey_id, types)
        with self._lock:
            missed = [e for e in self._history if last_event_id is not None and e["id"] > last_event_id]
            self._subs.add(sub)
        for event in missed:
            if sub.wants(event):
                sub.put(event)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subs.discard(sub)


def format_sse(event: dict) -> str:
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"


async def sse_stream(
    bus: EventBus,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    journey_id: str | None = None,
    types: frozenset[str] | None = None,
    last_event_id: int | None = None,
    heartbeat_s: float = 15.0,
) -> AsyncIterator[str]:
    """Yields SSE text: first a `ready` comment, then events, with a keep-alive
    comment every `heartbeat_s` so proxies don't close an idle connection."""
    sub = bus.subscribe(journey_id, types, last_event_id)
    try:
        yield "retry: 3000\n: connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=heartbeat_s)
            except asyncio.TimeoutError:
                if await is_disconnected():
                    return
                yield ": keep-alive\n\n"
                continue
            yield format_sse(event)
    finally:
        bus.unsubscribe(sub)
