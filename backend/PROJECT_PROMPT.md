# Project prompt: Walk Safety Backend (Cognitive Safety App)

Use this prompt to rebuild, extend, or explain the project. It describes the finished state of the `backend/` folder on branch `improve-risk-engine`.

---

## 1. Goal

Build a **FastAPI backend for a hackathon walking-safety app**. A person who may get confused while walking (for example, someone with early dementia, fictional user "Margaret") walks from a start point to a known destination ("Home" → "Tim Hortons", McGill area, Montreal). Their phone sends GPS points. The backend:

1. scores how worrying the walk looks right now (0–100, low / medium / high) with plain-language reasons,
2. sends Margaret a gentle **check-in** on her phone at medium risk,
3. raises a **caregiver alert** at high risk, when she presses a help button, or when her phone **stops sending GPS**,
4. **pushes** all of this live to a caregiver dashboard (Server-Sent Events, no polling).

Constraints:
- Prototype only. Fictional users, synthetic data. Every risk response carries a disclaimer: *not medically validated, not for real emergency monitoring*.
- Python 3.11+, FastAPI, Pydantic v2, httpx, python-dotenv. **No geo libraries.** Use haversine plus a local flat projection.
- In-memory storage. Everything works offline. Google Routes API is optional.
- Coordinates are always `{latitude, longitude}` objects. The stateless endpoints also accept `[lat, lng]` pairs.
- The journey's "now" is the **newest GPS timestamp**, so simulations replay instantly. The only exception is the no-signal watchdog, which uses the server's wall clock.

## 2. File layout

```
backend/
  app/
    main.py            FastAPI app factory, error handlers, CORS, endpoints, SSE route, watchdog lifespan
    config.py          Settings from env/.env (Google key, CORS, ROUTE_MODE, NO_SIGNAL_AFTER_S, WATCHDOG_INTERVAL_S)
    models.py          Pydantic request/response models and in-memory Journey state
    risk.py            Risk engine: GPS filtering, heading/progress/detour, rules, RiskConfig, evaluate()
    service.py         JourneyService: journeys, check-ins, alerts, dedup, no-signal watchdog, event publishing
    events.py          EventBus (thread-safe pub/sub with replay buffer) and the SSE stream generator
    routes_provider.py Route lookup: client route → predefined → Google Routes (WALK) → straight-line fallback
    geo.py             haversine, point-to-segment distance, polyline decode, offset/interpolate helpers
    demo.py            Scripted Tim Hortons scenario through the real service (python -m app.demo)
    simulate.py        Replays simulations/*.json through the stateless analyzer (python -m app.simulate)
    errors.py          ApiError → {"error": {"code","message","details"}}
  simulations/         normal.json, deviation.json, repeated_movement.json (stateless request bodies)
  viewer/index.html    Original demo map viewer
  viewer/scenarios.html Live demo page: 7 scenarios against the real API, plus the SSE caregiver feed
  tests/               pytest: test_api.py, test_reliability.py, test_live.py, test_heading.py (66 tests)
  API_CONTRACT.md      Contract for the frontend teammate
  README.md, requirements.txt, .env.example
```

## 3. GPS reliability (runs before any rule)

`filter_track(track, cfg)` splits readings into **reliable** ones, the latest unbroken **segment**, and a **discarded** count:
- `accuracy_m > 50` → discarded. Missing accuracy is trusted as exact, for backward compatibility.
- A timestamp equal to or earlier than the last reliable reading → discarded (duplicate).
- **Impossible jump:** distance from the last reliable reading > `4 m/s × Δt + both accuracies` → discarded. After **3 jumps in a row**, trust the new place and start a new segment (the old fix was wrong, or she took a bus).
- A **gap > 120 s** between reliable readings starts a new segment. Movement rules only use the latest segment. A single bad reading does *not* break the segment.
- `data_status = "ok"` if the last reliable reading is ≤ 120 s older than "now", otherwise `"insufficient_or_stale"`. A low score with stale data must never be shown as "safe".
- Movement rules (safe zone, off route, stationary, revisits) run only when the data is fresh **and** she is not at the destination (latest reliable reading within 50 m → `arrived: true`). Lateness still runs on stale data.

## 4. Movement summaries

- **Heading** (last 120 s of the segment, needs ≥ 30 s of span): `moved` = straight-line distance between the first and last points. If moved < 20 m → `stopped`. Otherwise `ratio = (dist_to_dest(first) − dist_to_dest(last)) / moved`: ≥ 0.5 → `toward`, ≤ −0.3 → `away`, else `sideways`. Too little data → `null`.
- **Progress / back on track** (window = from the last reading at least 5 min old until now): `progress_m` = metres closer to the destination. `making_progress = true` only if progress ≥ 30 m, **and** `progress / path walked ≥ 0.5` (a direct path, so a loop doesn't count), **and** she is now closer than at every earlier point in the last 15 min (coming round a loop to the same corner is not progress). Too early → `null`.
- **Detour minutes** (only when off route and heading toward): `elapsed + remaining − planned`. Here `remaining = straight-line distance to destination × 1.3 / pace` and `planned = route_duration_s`, or route length at 1.3 m/s. `pace = route length / planned`. Clamped at ≥ 0.

## 5. Risk rules

The score is **recomputed from scratch on every update** (never accumulated), capped at 100. Levels: **low < 30 ≤ medium < 60 ≤ high**.

| Code | Points | Condition |
|---|---|---|
| `left_safe_zone` | 15 | She arrived inside a safe zone that doesn't contain the start, and the latest reliable point is now outside every such zone |
| `off_route` | **5–30 by direction** | The last 3 reliable readings are all > 100 m from the route polyline **after subtracting each reading's accuracy** |
| ↳ heading `toward` | 5, +5 per 5 extra detour minutes, max 20 | "Taking a different way (210 m from the planned route) but heading towards Tim Hortons; about 3 min longer than planned." |
| ↳ `sideways` / unknown | 25 | "Off the route (… m) and not getting closer to Tim Hortons." |
| ↳ `away` | 30 | "Off the route (… m) and walking away from Tim Hortons." |
| ↳ `stopped` | 30 | "Off the route (… m) and not moving." |
| `stationary` | 15 | Within 25 m of the latest point for > 5 min (never at the destination) |
| `repeated_revisits` | 25 | ≥ 3 revisits **within the last 15 min**, and not back on track (see below) |
| `late_arrival` | 20 | > 10 min past `expected_arrival` and no reliable reading ever within 50 m of the destination |

**Revisits:** keep "anchor" places (a new anchor when a point is > 30 m from all existing anchors). Changing to a previously visited anchor = one revisit. Stepping back to the immediately previous anchor (a single turn-around) is backtracking and doesn't count. Revisits are suppressed if `making_progress` is true, **or** if she is ≥ 30 m closer to the destination than at any point before the repeating started.

`recommended_action`: low → `continue_monitoring`, medium → `contextual_check_in`, high → `caregiver_alert`, help pressed → `immediate_caregiver_alert`.

Every threshold and point value lives in a frozen `RiskConfig` dataclass. All values must be positive. `medium_min < high_min`, and off-route points must grow: toward-max ≤ sideways ≤ away/stopped. `create_app(risk_config=...)` and `JourneyService(..., risk_config)` accept overrides. `evaluate(track=, route=, start=, destination=, expected_arrival=, safe_zones=, help_requested=, now=, started_at=, expected_duration_s=, cfg=)` is a pure function used by both the stateful and stateless APIs.

**Risk object fields:** `score, level, reasons[{code, points, description}], recommended_action, help_requested, evaluated_at, data_status, arrived, distance_from_route_m, accepted_readings, discarded_readings, heading, detour_extra_min, making_progress, progress_m, disclaimer`.

## 6. Escalation (JourneyService)

- **Medium:** create one check-in (*"Hi Margaret, you're on your way to Tim Hortons. …"*, options *I'm okay / Show me the way / I need help*). There's a 10-minute journey-time cooldown, and never while one is still open. The wording depends on the reason and direction: away / stopped off route / different way / loops / stopped / late.
- **High:** one unacknowledged `risk` alert per journey (priority `high`). It latches while the level stays high, so it isn't re-raised. When there's nothing new to raise, `deduplicated: true`.
- **Help button** (`POST /checkin {"help_requested": true}`): a `help_request` alert with priority `critical`, deduplicated while unacknowledged.
- **No-signal watchdog:** a background asyncio task (started in the FastAPI lifespan) runs every `WATCHDOG_INTERVAL_S` (15 s). For each **active** journey with `signal_watch=true` whose `last_seen_at` (server wall-clock time of the last GPS receipt) is older than `NO_SIGNAL_AFTER_S` (300 s), it raises one `no_signal` alert (priority `high`): *"No location from Margaret for 6 minutes on the way to Tim Hortons. Last known position 45.50480, -73.57720. Their phone may be off, out of battery or without signal."* (seconds if under 90 s).
  - When GPS comes back or the journey ends, the alert gets `resolved_at` and an `alert_resolved` event is sent.
  - Acknowledging doesn't fix silence: the next check raises a new alert if she's still silent.
  - `signal_watch: false` disables it (the demo replay uses this). `NO_SIGNAL_AFTER_S=0` turns the watchdog off.
- Service state changes are serialised with an `RLock`, because endpoints run in a thread pool while the watchdog runs on the event loop. The Google route lookup happens outside the lock.

## 7. Live events (Server-Sent Events)

- `EventBus.publish(type, journey_id, data)` is thread-safe and delivers to subscribers with `loop.call_soon_threadsafe`.
- Each subscriber has a queue of 200; when full, the oldest event is dropped. A replay buffer keeps the last 500 events for `Last-Event-ID` reconnects.
- `Subscriber` is `@dataclass(eq=False)` so it hashes by identity.
- Event types: `risk_updated` (every GPS update: `{journey_id, location, risk}`), `checkin_created`, `checkin_answered`, `alert_created`, `alert_acknowledged`, `alert_resolved`, `journey_ended`.
- Payload: `{id, type, journey_id, sent_at, data}`.
- `GET /api/events?journey_id=&types=a,b` streams `text/event-stream`. It starts with `retry: 3000`, sends `: keep-alive` every 15 s, and closes when the client disconnects. Unknown types → 422 `unknown_event_type`.
- Frontend: `new EventSource("/api/events?types=alert_created,alert_resolved")`.

## 8. API (all under `/api`, JSON, uniform errors `{"error":{"code","message","details"}}`)

| Method / path | Purpose |
|---|---|
| `GET /health` | status, google_routes_configured, route_mode, no_signal_after_s, live_subscribers, disclaimer |
| `POST /journeys` (201) | user_name, start, destination, expected_arrival, optional route / predefined_route / safe_zones / started_at / `signal_watch` |
| `GET /journeys`, `GET /journeys/{id}` | Journey (track, latest_location, risk, route_source, route_warning, signal_watch, last_seen_at, …) |
| `POST /journeys/{id}/location` | `{latitude, longitude, timestamp?, accuracy_m?}` → `{risk, checkin_created, alert_created, deduplicated}`. Timestamps earlier than the previous one → 422 `out_of_order_timestamp`. Ended journey → 409 |
| `GET /journeys/{id}/checkins`, `POST /journeys/{id}/checkin` | answer a check-in (`response`, `checkin_id?`) or `help_requested` |
| `POST /journeys/{id}/complete` · `/cancel` | end the journey, close check-ins, resolve no-signal alerts |
| `GET /alerts?journey_id=&acknowledged=` · `POST /alerts/{id}/acknowledge` | alerts, newest first: `type` risk / help_request / no_signal, `resolved_at` |
| `GET /events` | live SSE stream |
| `POST /analyze-journey` | **stateless**: `{journey_id?, gps_history[{latitude, longitude, timestamp (unix or ISO), accuracy_meters}], expected_route ([lat,lng] or objects), destination?, expected_arrival?, started_at?, expected_duration_s?, now?, safe_zones?}` → `{journey_id, risk}`. Unsorted history → 422 `out_of_order_timestamp`; `now` earlier than the last reading → 422 `invalid_now` |
| `POST /expected-route` | `{start, destination}` → `{route, route_source, route_warning, distance_m, duration_s}` |
| `GET /routes/predefined`, `POST /demo/run`, `POST /demo/reset` | demo helpers |
| `/viewer/`, `/viewer/scenarios.html` | demo pages served by the backend |

**Route choice:** client `route` → `predefined_route` (`tim_hortons_demo`) → Google Routes `computeRoutes` (travelMode WALK, field mask distanceMeters, duration, polyline). Any Google failure (no key, HTTP error, network error, empty result) falls back to a straight line with a `route_warning`, and never crashes.

## 9. Demo page (`viewer/scenarios.html`)

A single static page served by the backend. It posts simulated GPS points (one per 30 s of walk time, at 1.3 m/s, accuracy 8 m) to the real API.

Layout:
- scenario cards across the top
- SVG map: route, 100 m band, destination circle, trail coloured by level, ✕ for discarded readings
- risk panel: score, level, reasons with points, chips for direction / back on track / detour minutes / GPS status, score sparkline
- phone mock with clickable check-in answers
- caregiver feed from `EventSource`, with Acknowledge buttons

Scenarios and their checked outcomes:
1. **Normal walk:** stays at 0 and arrives.
2. **Another street, right way:** off route but heading toward, +5, "+4 min" detour.
3. **Walks the wrong way:** away, 30 → medium, and a "heading away" check-in.
4. **Circles, then finds the way:** rises to 55 (medium), then falls to 0 with "back on track".
5. **Bad GPS:** three 700 m spikes and two ±90 m readings are discarded, with no alarm.
6. **Phone goes quiet:** a no-signal alert is pushed live, then "Signal back".
7. **Lost and stopped:** check-in, then a 70/100 high caregiver alert.

Every scenario completes its journey at the end. Only scenario 6 has `signal_watch` on.

## 10. Tests (pytest, 66 passing)

- `test_api.py`: CRUD, errors, each rule, safe zones, check-in once + dedup, help alert, high alert dedup + acknowledge, CORS, demo, Google mocked via `httpx.MockTransport`.
- `test_reliability.py`: spike ignored, inaccurate readings discarded, accuracy subtracted from route distance, 3-jump reset, gap breaks stationary, accuracy stored, loop + progress, RiskConfig overrides/validation, the three simulations via `/analyze-journey`, stale data keeps lateness, ISO/object input + order validation, `/expected-route` fallback.
- `test_live.py`: no-signal after 5 min (once), resolve on GPS return + re-arm, acknowledged ≠ fixed, skipped for ended / unwatched / demo journeys, ending resolves it, the real lifespan watchdog fires, every action publishes the right events, unknown event type → 422, bus filtering + Last-Event-ID replay, slow subscriber keeps the newest 200, SSE framing + keep-alive + cleanup.
- `test_heading.py`: toward = 5 and low, detour points 5 / 15 / 20 as minutes grow, toward 5 < sideways 25 < away 30 = stopped 30, away check-in wording, heading needs history, circles twice then finds the way → low with `making_progress`, loops older than 15 min expire, progress in the stateless analysis.

## 11. Run

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q                                   # 66 passed
python -m app.demo                                    # terminal replay
python -m app.simulate                                # score simulations/*.json
python -m uvicorn app.main:app --reload               # http://localhost:8000/docs
# live demo with a short no-signal timer:
ROUTE_MODE=offline NO_SIGNAL_AFTER_S=10 WATCHDOG_INTERVAL_S=2 python -m uvicorn app.main:app
# then open http://localhost:8000/viewer/scenarios.html
```

`.env` (copy from `.env.example`): `GOOGLE_MAPS_API_KEY`, `CORS_ORIGINS`, `ROUTE_MODE=auto|offline`, `NO_SIGNAL_AFTER_S=300`, `WATCHDOG_INTERVAL_S=15`. Never commit `.env`.

## 12. Known limits / next ideas

- In-memory and single-process: a restart loses everything, and several workers would need Redis (or similar) for state and events. SQLite is the next step.
- No authentication: anyone can read alerts. Add at least a caregiver token.
- Heading and detour use straight-line distance to the destination, not the street network.
- Thresholds and point values are illustrative, not clinically validated.
- Ideas: street-name guidance in check-ins, learning each person's normal pace and routes, battery level in no-signal alerts.
