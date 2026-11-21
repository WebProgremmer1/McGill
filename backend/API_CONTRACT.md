# API Contract (hackathon prototype)

Base URL (local): `http://localhost:8000`. All paths start with `/api`. JSON in, JSON out.
CORS allows `http://localhost:5173` (and `127.0.0.1:5173`). Interactive docs: `http://localhost:8000/docs`.

> Experimental navigation-risk heuristics on fictional/synthetic data. **Not** medically validated, **not** for real emergency monitoring.

Conventions
- Coordinates are `{ "latitude": number, "longitude": number }` (lat −90..90, lng −180..180).
- Timestamps are ISO-8601 UTC, e.g. `"2026-01-01T09:00:00Z"`. Naive times are treated as UTC.
- IDs are strings: `jrn_…` (journey), `chk_…` (check-in), `alt_…` (alert).
- The journey's "now" is the **newest GPS timestamp**, so you can send simulated timestamps.

## Risk levels

| Level  | Score  | What happens                                   | `recommended_action`        |
|--------|--------|------------------------------------------------|-----------------------------|
| low    | 0–29   | Keep monitoring                                | `continue_monitoring`       |
| medium | 30–59  | A contextual check-in is created (once; 10 min cooldown) | `contextual_check_in` |
| high   | 60–100 | One caregiver alert (priority `high`)          | `caregiver_alert`           |
| —      | —      | User pressed help → alert priority `critical`  | `immediate_caregiver_alert` |
| —      | —      | No GPS received for 5 minutes → `no_signal` alert (priority `high`) | — |

Score is **recalculated from current conditions on every update** (not accumulated):

| Reason code         | Points | Condition |
|---------------------|--------|-----------|
| `left_safe_zone`    | +15 | She arrived inside a safe zone (that does not contain the journey start) and is now outside it. Leaving the start/home zone never scores. |
| `off_route`         | +5 … +30 | Last 3 reliable GPS updates all > 100 m from the route (after subtracting each reading's `accuracy_m`). Points depend on direction, see below |
| `stationary`        | +15 | Within 25 m for > 5 minutes (not counted at the destination) |
| `repeated_revisits` | +25 | Returned to previously visited places ≥ 3 times **in the last 15 minutes** (simple turn-arounds don't count), and not back on track (see below) |
| `late_arrival`      | +20 | > 10 minutes past `expected_arrival` and not within 50 m of destination |

### Off route: direction matters
Direction is judged over the last 2 minutes, relative to the destination (`risk.heading`):

| `heading` | Meaning | `off_route` points |
|---|---|---|
| `toward` | Another street, but getting closer | 5, +5 per 5 extra minutes the detour adds (max 20). `risk.detour_extra_min` holds the estimate |
| `sideways` | Moving, but not getting closer or farther | 25 |
| `away` | Getting farther from the destination | 30 → medium on its own → check-in |
| `stopped` | Moved < 20 m in 2 minutes | 30 |

Extra minutes = time walked so far + remaining straight-line distance × 1.3 at the route's pace − the route's planned time (`route_duration_s`, or route length at 1.3 m/s).

### Back on track
`risk.making_progress` is `true` when, over the last 5 minutes, she got ≥ 30 m closer, on a fairly direct path, and is closer than anywhere she was in the last 15 minutes (so coming round a loop again doesn't count). `progress_m` is the metres gained. While she is making progress, earlier loops stop scoring; loops older than 15 minutes never score. `null` = too early to tell.

### GPS reliability (applied before any rule)
- Readings with `accuracy_m` > 50 m are ignored. **Send `accuracy_m`** (browser: `pos.coords.accuracy`); readings without it are trusted as exact.
- A reading implying > 4 m/s (allowing for both readings' accuracy) is ignored as a GPS jump. Three jumps in a row to a consistent new place are accepted (the old fix was wrong).
- A gap > 120 s between reliable readings breaks the evidence chain: off route / stationary / revisits only use the latest unbroken stretch.
- Movement rules are skipped while the latest reliable reading is within 50 m of the destination (`arrived: true`) or older than 120 s.

Every `risk` object also carries:
```json
{ "data_status": "ok", "arrived": false, "distance_from_route_m": 374.1,
  "accepted_readings": 7, "discarded_readings": 0,
  "heading": "toward", "detour_extra_min": 3.2, "making_progress": true, "progress_m": 310.5 }
```
`data_status: "insufficient_or_stale"` means there is no recent reliable GPS. **Never show a low score with stale data as "safe"**; show "location unknown" instead. `late_arrival` can still fire while stale.

## Errors

Every error has the same shape:
```json
{ "error": { "code": "journey_not_found", "message": "No journey with id 'x'.", "details": null } }
```
| HTTP | code | When |
|------|------|------|
| 404 | `journey_not_found`, `alert_not_found`, `checkin_not_found`, `no_open_checkin` | Unknown id / nothing to answer |
| 409 | `journey_not_active` | Location/check-in/complete on a completed or cancelled journey |
| 422 | `validation_error` | Bad body, e.g. latitude 91. `details` = `[{"field","message"}]` |
| 422 | `out_of_order_timestamp` | GPS timestamp older than the previous one |
| 422 | `unknown_predefined_route` | `details.available` lists valid names |
| 422 | `invalid_now` | `/api/analyze-journey`: `now` earlier than the last GPS reading |

---

## `GET /api/health`
```json
{ "status": "ok", "google_routes_configured": false, "route_mode": "auto", "disclaimer": "…" }
```

## `POST /api/journeys` → 201
Request (`route` and `predefined_route` are optional; `started_at` is optional, handy for simulations):
```json
{
  "user_name": "Margaret",
  "start": { "name": "Home", "latitude": 45.5048, "longitude": -73.5772 },
  "destination": { "name": "Tim Hortons", "latitude": 45.5088, "longitude": -73.5697 },
  "expected_arrival": "2026-01-01T09:15:00Z",
  "safe_zones": [
    { "name": "Home", "latitude": 45.5048, "longitude": -73.5772, "radius_m": 75 },
    { "name": "Tim Hortons", "latitude": 45.5088, "longitude": -73.5697, "radius_m": 75 }
  ],
  "predefined_route": "tim_hortons_demo"
}
```
Route choice order: `route` (client) → `predefined_route` → Google Routes (walking) → straight-line fallback.
Calculated once, at creation.

Response = a **Journey** (also returned by GET/complete/cancel):
```json
{
  "id": "jrn_1a2b3c4d", "user_name": "Margaret", "status": "active",
  "start": {…}, "destination": {…},
  "expected_arrival": "2026-01-01T09:15:00Z", "started_at": "2026-01-01T09:00:00Z", "ended_at": null,
  "route": [ { "latitude": 45.5048, "longitude": -73.5772 }, … ],
  "route_source": "predefined",
  "route_warning": null,
  "route_distance_m": null, "route_duration_s": null,
  "safe_zones": [ … ],
  "track": [ { "latitude": …, "longitude": …, "timestamp": "…" } ],
  "latest_location": null,
  "help_requested": false,
  "risk": {
    "score": 0, "level": "low", "reasons": [],
    "recommended_action": "continue_monitoring", "help_requested": false,
    "evaluated_at": "2026-01-01T09:00:00Z", "disclaimer": "…"
  }
}
```
`route_source`: `client` | `predefined` | `google_routes` | `fallback_straight_line`. When it is the fallback, `route_warning` says why (missing key, API error…).

## `GET /api/journeys` → `Journey[]`  ·  `GET /api/journeys/{id}` → `Journey`

## `POST /api/journeys/{id}/location`
Request (`timestamp` optional → server time; `accuracy_m` optional but recommended):
```json
{ "latitude": 45.5060, "longitude": -73.5754, "timestamp": "2026-01-01T09:01:00Z", "accuracy_m": 12 }
```
Response:
```json
{
  "journey_id": "jrn_1a2b3c4d", "journey_status": "active",
  "location": { "latitude": 45.506, "longitude": -73.5754, "timestamp": "2026-01-01T09:01:00Z" },
  "risk": {
    "score": 50, "level": "medium",
    "reasons": [
      { "code": "off_route", "points": 25, "description": "372 m away from the expected route (limit 100 m)." },
      { "code": "repeated_revisits", "points": 25, "description": "Has returned to previously visited locations 3 times." }
    ],
    "recommended_action": "contextual_check_in", "help_requested": false,
    "evaluated_at": "2026-01-01T09:13:00Z", "disclaimer": "…"
  },
  "checkin_created": { "id": "chk_…", "status": "open", "message": "Hi Margaret, …", "options": ["I'm okay","Show me the way","I need help"], … },
  "alert_created": null,
  "deduplicated": false
}
```
`checkin_created` / `alert_created` are non-null only on the update that created them. `deduplicated: true` = an escalation was due but suppressed because one already exists.

## `GET /api/journeys/{id}/checkins` → `CheckIn[]`
```json
{ "id": "chk_9f8e7d6c", "journey_id": "jrn_…", "created_at": "2026-01-01T09:13:00Z",
  "status": "open", "message": "Hi Margaret, you're on your way to Tim Hortons. …",
  "options": ["I'm okay", "Show me the way", "I need help"],
  "risk_score": 50, "reason_codes": ["off_route","repeated_revisits"],
  "response": null, "answered_at": null }
```
`status`: `open` | `answered` | `closed` (journey ended).

## `POST /api/journeys/{id}/checkin`
Answer the latest open check-in (or the one in `checkin_id`):
```json
{ "response": "I'm okay" }
```
→ `{ "journey_id": "…", "risk": {…}, "checkin": { …"status":"answered" }, "alert": null, "deduplicated": false }`

Explicit help request (immediate critical alert; repeating while unacknowledged returns the same alert with `deduplicated: true`):
```json
{ "help_requested": true }
```
→ `{ "journey_id": "…", "risk": { …"recommended_action": "immediate_caregiver_alert" }, "checkin": null,
   "alert": { "type": "help_request", "priority": "critical", … }, "deduplicated": false }`

## `POST /api/journeys/{id}/complete` · `POST /api/journeys/{id}/cancel` → `Journey`
No body. Sets `status` to `completed` / `cancelled`; open check-ins become `closed`.

## `GET /api/alerts?journey_id=&acknowledged=` → `Alert[]` (newest first)
```json
{ "id": "alt_5c4b3a29", "journey_id": "jrn_…", "user_name": "Margaret",
  "type": "risk", "priority": "high",
  "message": "Margaret may need assistance on the way to Tim Hortons. Risk 65/100 (…)",
  "risk_score": 65, "risk_level": "high",
  "reasons": [ { "code": "stationary", "points": 15, "description": "…" } ],
  "location": { "latitude": …, "longitude": …, "timestamp": "…" },
  "created_at": "2026-01-01T09:20:00Z", "acknowledged": false, "acknowledged_at": null }
```
`type`: `risk` | `help_request` | `no_signal`; `priority`: `high` | `critical`.
Only **one** unacknowledged risk alert exists per journey, and no new one is raised while the risk stays high.

### No-signal alerts
If an active journey receives **no GPS update for 5 minutes** (server clock, not GPS timestamps), the server raises one `no_signal` alert:
`"No location from Margaret for 6 minutes on the way to Tim Hortons. Last known position 45.50480, -73.57720. Their phone may be off, out of battery or without signal."`
- When GPS comes back (or the journey ends), the alert gets `resolved_at` and an `alert_resolved` event is pushed. It stays in the list until acknowledged.
- Acknowledging does not fix the silence: if the phone is still quiet on the next check, a new alert is raised.
- Turn it off per journey with `"signal_watch": false` in `POST /api/journeys` (the demo replay does this). Journeys expose `signal_watch` and `last_seen_at`.
- Server settings: `NO_SIGNAL_AFTER_S` (default 300, `0` = off) and `WATCHDOG_INTERVAL_S` (default 15).

## `GET /api/events` (live push, Server-Sent Events)
Keep one connection open instead of polling. Optional filters: `?journey_id=jrn_…` and `?types=alert_created,alert_resolved`.
Each message has an `event:` name and JSON `data`:
```json
{ "id": 12, "type": "alert_created", "journey_id": "jrn_…", "sent_at": "2026-…Z", "data": { …the Alert… } }
```
| `type` | `data` |
|---|---|
| `alert_created` | Alert (`risk`, `help_request` or `no_signal`) |
| `alert_acknowledged` / `alert_resolved` | Alert |
| `checkin_created` / `checkin_answered` | CheckIn |
| `risk_updated` | `{ journey_id, location, risk }` after every GPS update |
| `journey_ended` | `{ journey_id, status, ended_at }` |

The browser's `EventSource` reconnects by itself and sends `Last-Event-ID`; missed events (last 500) are replayed. A `: keep-alive` comment is sent every 15 s. Unknown `types` → 422 `unknown_event_type`.

## `POST /api/alerts/{id}/acknowledge` → `Alert`
No body. Idempotent.

## Stateless endpoints (nothing stored)
### `POST /api/analyze-journey`
Score a whole GPS history in one call, with the same engine as `/location`. Body = a file in `simulations/`:
```json
{ "journey_id": "deviation",
  "expected_route": [[45.5017, -73.5673], [45.5057, -73.5673]],
  "gps_history": [ { "latitude": 45.5017, "longitude": -73.5673, "timestamp": 1805756400, "accuracy_meters": 5 } ],
  "destination": null, "expected_arrival": null, "now": null, "safe_zones": [] }
```
Route points may be `[lat, lng]` pairs or `{latitude, longitude}`. `timestamp`, `expected_arrival` and `now` accept Unix seconds or ISO-8601. `destination` defaults to the last route point. Optional `started_at` (default: first reading) and `expected_duration_s` (e.g. `duration_s` from `/api/expected-route`) improve the detour-minutes estimate. Leave `now` empty to replay (uses the last GPS time); send the real time for live tracking.
→ `{ "journey_id": "deviation", "risk": { …same shape as above… } }`

### `POST /api/expected-route`
`{ "start": [45.5048, -73.5772], "destination": [45.5088, -73.5697] }` → `{ "route": [...], "route_source", "route_warning", "distance_m", "duration_s" }`

## Extras
- `GET /api/routes/predefined` → `{ "routes": ["tim_hortons_demo"] }`
- `POST /api/demo/run` → replays the Tim Hortons scenario instantly through the real risk engine:
  `{ "journey_id", "summary": {first_medium_at_minute, first_high_at_minute, final_score, …}, "steps": [ {minute, phase, description, latitude, longitude, score, level, reasons[], checkin_created, alert_created} ] }`.
  The journey, check-in and alert then show up in the normal GET endpoints.
- `POST /api/demo/reset` → clears all in-memory data.

## Frontend integration examples
```js
const API = "http://localhost:8000/api";
const post = (path, body) => fetch(`${API}${path}`, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: body ? JSON.stringify(body) : undefined,
}).then(async r => { const j = await r.json(); if (!r.ok) throw j.error; return j; });

// start a journey
const journey = await post("/journeys", {
  user_name: "Margaret",
  start: { name: "Home", latitude: 45.5048, longitude: -73.5772 },
  destination: { name: "Tim Hortons", latitude: 45.5088, longitude: -73.5697 },
  expected_arrival: new Date(Date.now() + 15 * 60000).toISOString(),
  predefined_route: "tim_hortons_demo",   // omit to use Google Routes
});

// send GPS (e.g. from navigator.geolocation.watchPosition)
const res = await post(`/journeys/${journey.id}/location`, {
  latitude: pos.coords.latitude, longitude: pos.coords.longitude,
  timestamp: new Date(pos.timestamp).toISOString(), accuracy_m: pos.coords.accuracy,
});
if (res.checkin_created) showCheckIn(res.checkin_created);

// help button
await post(`/journeys/${journey.id}/checkin`, { help_requested: true });

// caregiver dashboard: load current alerts once, then listen live (no polling)
let alerts = await fetch(`${API}/alerts?acknowledged=false`).then(r => r.json());
const live = new EventSource(`${API}/events?types=alert_created,alert_resolved,alert_acknowledged`);
live.addEventListener("alert_created", e => showAlert(JSON.parse(e.data).data));
live.addEventListener("alert_resolved", e => markResolved(JSON.parse(e.data).data));   // phone is back
await post(`/alerts/${alerts[0].id}/acknowledge`);

// one-click demo: animate res.steps on a map
const demo = await post("/demo/run");
```
