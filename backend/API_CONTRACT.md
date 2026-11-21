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

Score is **recalculated from current conditions on every update** (not accumulated):

| Reason code         | Points | Condition |
|---------------------|--------|-----------|
| `off_route`         | how far (50–150 m: 10, 150–300 m: 25, over 300 m: 40) + how long (2 per minute off route, max 40) | More than 50 m from the route |
| `stationary`        | 3 per minute after the first 2, max 25 | Stayed within 25 m (not counted at the destination) |
| `repeated_revisits` | 15 per return, max 30 | Times she came back to her current spot (within 30 m) |
| `left_safe_zone`    | 15 | Reached a safe zone (not the start/Home zone) and then left it |
| `taking_too_long`   | 2 per minute over the allowed time, max 30 | Allowed time = 1.5 × (`expected_arrival` − `started_at`). Stops once she reaches the destination |
| `ignored_checkin`   | 15 | A check-in has been unanswered for 2+ minutes and she has moved more than 25 m since it was sent. Any answer removes it |
| `said_okay`         | −15 | For the rest of the walk once she answers "I'm okay" (does not stack; score never below 0) |

See the README for the full rules.

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
Route choice order: `route` (client) → `predefined_route` → Google Routes (walking) → `fallback_route` (a predefined route, if sent) → straight-line fallback.
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
Request (`timestamp` optional → server time):
```json
{ "latitude": 45.5060, "longitude": -73.5754, "timestamp": "2026-01-01T09:01:00Z" }
```
Response:
```json
{
  "journey_id": "jrn_1a2b3c4d", "journey_status": "active",
  "location": { "latitude": 45.506, "longitude": -73.5754, "timestamp": "2026-01-01T09:01:00Z" },
  "risk": {
    "score": 48, "level": "medium",
    "reasons": [
      { "code": "off_route", "points": 33, "description": "Off route (247 m away) for 4 min." },
      { "code": "repeated_revisits", "points": 15, "description": "Came back to this spot 1 time(s)." }
    ],
    "recommended_action": "contextual_check_in", "help_requested": false,
    "evaluated_at": "2026-01-01T09:13:00Z", "disclaimer": "…"
  },
  "checkin_created": { "id": "chk_…", "status": "open", "message": "Hi Margaret, …", "options": ["I'm okay","I need help"], … },
  "alert_created": null,
  "deduplicated": false
}
```
`checkin_created` / `alert_created` are non-null only on the update that created them. `deduplicated: true` = an escalation was due but suppressed because one already exists.

## `GET /api/journeys/{id}/checkins` → `CheckIn[]`
```json
{ "id": "chk_9f8e7d6c", "journey_id": "jrn_…", "created_at": "2026-01-01T09:13:00Z",
  "status": "open", "message": "Hi Margaret, you're on your way to Tim Hortons. …",
  "options": ["I'm okay", "I need help"],
  "risk_score": 48, "reason_codes": ["off_route","repeated_revisits"],
  "response": null, "answered_at": null }
```
`status`: `open` | `answered` | `closed` (journey ended).

## `POST /api/journeys/{id}/checkin`
Answer the latest open check-in (or the one in `checkin_id`):
```json
{ "response": "I'm okay" }
```
→ `{ "journey_id": "…", "risk": {…}, "checkin": { …"status":"answered" }, "alert": null, "deduplicated": false }`

When the answer is "I'm okay", `risk` already includes the −15, and `alert` is a caregiver notice:
`{ "type": "said_okay", "priority": "info", "message": "Margaret answered \"I'm okay\" at 2:36 PM, 6 min into the walk to Tim Hortons. Risk is now 26/100.", … }`

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
`type`: `risk` | `help_request` | `said_okay`; `priority`: `info` | `high` | `critical`.
Only **one** unacknowledged risk alert exists per journey, and no new one is raised while the risk stays high.

## `POST /api/alerts/{id}/acknowledge` → `Alert`
No body. Idempotent.

## `GET /api/messages` → `Message[]` (newest first)  ·  `POST /api/messages` → 201
Ordinary demo messages to a caregiver. They are kept in memory, cleared by `POST /api/demo/reset`, and never create alerts or journeys.
```json
{ "body": "I got home safely." }
```
→ `{ "id": "msg_1a2b3c4d", "body": "I got home safely.", "created_at": "2026-01-01T09:20:00Z" }`

`body` is 1 to 280 characters after trimming.

## Extras
- `GET /api/routes/predefined` → `{ "routes": ["tim_hortons_demo"] }`
- `POST /api/demo/run` → replays the Tim Hortons scenario instantly through the real risk engine:
  `{ "journey_id", "summary": {first_medium_at_minute, first_high_at_minute, final_score, …}, "steps": [ {minute, phase, description, latitude, longitude, score, level, reasons[], reason_details[], checkin_created, alert_created} ] }`.
  The journey, check-in and alert then show up in the normal GET endpoints.
- `POST /api/demo/reset` → clears all in-memory data.
- `GET /api/maps-config` → `{ "browser_key": "…" | null, "maps_enabled": true }`, the separate browser key for Google Maps. It is `null` if blank or the same as the server key.
- `POST /api/expected-route` with `{ "start": {latitude, longitude}, "destination": {latitude, longitude} }` →
  `{ "route": [ {latitude, longitude}, … ], "route_source", "route_warning", "distance_m", "duration_s" }`. Looks up a route without creating a journey.

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
  timestamp: new Date(pos.timestamp).toISOString(),
});
if (res.checkin_created) showCheckIn(res.checkin_created);

// help button
await post(`/journeys/${journey.id}/checkin`, { help_requested: true });

// caregiver dashboard: poll every few seconds
const alerts = await fetch(`${API}/alerts?acknowledged=false`).then(r => r.json());
await post(`/alerts/${alerts[0].id}/acknowledge`);

// one-click demo: animate res.steps on a map
const demo = await post("/demo/run");
```
