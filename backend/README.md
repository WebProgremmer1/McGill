# Cognitive Safety Backend (hackathon prototype)

FastAPI backend for a walking-safety app. Fictional users / synthetic data only. **Experimental heuristics, not medically validated, not for real emergency monitoring.**

## Run it (from this `backend` folder, PowerShell)
```powershell
pip install -r requirements.txt          # once
python -m pytest -q                      # run tests (66 should pass)
python -m app.demo                       # replay the demo in the terminal
python -m app.simulate                   # score simulations/*.json (stateless analyzer)
python -m uvicorn app.main:app --reload  # start the API
```
Then open **http://localhost:8000/docs** (interactive API page). Try `POST /api/demo/run` -> "Try it out" -> "Execute", then `GET /api/alerts`.
Share `API_CONTRACT.md` with your frontend teammate.

## Google Maps setup (optional: everything works offline without it)
1. Go to https://console.cloud.google.com, select (or create) your project, and make sure **billing is enabled** (Routes API requires a billing account; Google gives free monthly usage).
2. **APIs & Services -> Library -> search "Routes API" -> Enable.** This is the only API the backend needs. (Enable "Maps JavaScript API" only for your teammate's frontend map, and ideally use a *separate* key for that.)
3. **APIs & Services -> Credentials -> your key -> API restrictions -> Restrict key -> Routes API.** (Do not use an HTTP-referrer restriction on this server-side key; the backend isn't a browser.)
4. In this folder copy `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```
   Open `.env` in VS Code and paste your key after `GOOGLE_MAPS_API_KEY=` (no quotes, no spaces). `.env` is git-ignored.
5. Restart uvicorn. `GET /api/health` should show `"google_routes_configured": true`.
6. Create a journey **without** `predefined_route` / `route`; the response's `route_source` will be `google_routes`. If anything fails (bad key, API not enabled, no network) you get `fallback_straight_line` plus a `route_warning` explaining why; the app keeps working.

Set `ROUTE_MODE=offline` in `.env` to never call Google.

## Live map demo (real Montreal streets)
Start the API (see above), then open **http://localhost:8000/** (redirects to `/viewer/live-map.html`).
- Pick a start and a destination: search box (Google Places, limited to Montreal), **Pick on map**, drag the A/B pins, or one of the presets.
- The backend fetches a real walking route from Google (`POST /api/expected-route`) and draws it with the 100 m "on route" band.
- Each scenario card simulates a walk on that route (normal, detour, wrong way, loops, bad GPS, phone goes quiet, lost and stopped) and posts GPS points to the real API. The trail is coloured by risk level; the phone and the caregiver feed react live.
- The page gets its browser key from `GET /api/maps-config` (`GOOGLE_MAPS_BROWSER_KEY`, or `GOOGLE_MAPS_API_KEY` if that is blank). That key needs **Maps JavaScript API** and **Places API**; the backend key needs **Routes API**. Since a browser key is always visible to visitors, restrict it by HTTP referrer (e.g. `http://localhost:8000/*`) and use a separate, unrestricted-by-referrer key for the server if you split them.
- Quick no-signal demo: `NO_SIGNAL_AFTER_S=10 WATCHDOG_INTERVAL_S=2 python -m uvicorn app.main:app`.
- The old diagram version (no Google needed) is still at `/viewer/scenarios.html`.

## Live alerts
`GET /api/events` is a live stream (Server-Sent Events): the dashboard gets alerts the moment they happen. Try it in a second terminal: `curl -N http://localhost:8000/api/events`.
If a journey sends no GPS for 5 minutes the caregiver gets a `no_signal` alert. For a quick demo set `NO_SIGNAL_AFTER_S=30` in `.env`.

## Layout
```
app/main.py            API endpoints, error handling, CORS
app/models.py          Pydantic request/response models
app/risk.py            risk engine: GPS filtering + scoring rules, thresholds in RiskConfig
app/service.py         journeys, check-ins, alerts, deduplication, no-signal watchdog (in-memory)
app/events.py          live event bus + Server-Sent Events stream
app/routes_provider.py Google Routes + predefined/fallback routes
app/geo.py             distance maths, polyline decoding
app/demo.py            scripted Tim Hortons simulation
app/simulate.py        replays simulations/*.json
simulations/           sample journeys for POST /api/analyze-journey
tests/                 pytest suite
viewer/live-map.html   live demo on a real Google map (main demo page)
viewer/scenarios.html  same scenarios on an offline diagram
```
