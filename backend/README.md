# Cognitive Safety Backend (hackathon prototype)

FastAPI backend for a walking-safety app. Fictional users / synthetic data only. **Experimental heuristics, not medically validated, not for real emergency monitoring.**

## Run it (from this `backend` folder, PowerShell)
```powershell
pip install -r requirements.txt          # once
python -m pytest -q                      # run tests (31 should pass)
python -m app.demo                       # replay the demo in the terminal
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

## Layout
```
app/main.py            API endpoints, error handling, CORS
app/models.py          Pydantic request/response models
app/risk.py            risk engine (all scoring rules live here)
app/service.py         journeys, check-ins, alerts, deduplication (in-memory)
app/routes_provider.py Google Routes + predefined/fallback routes
app/geo.py             distance maths, polyline decoding
app/demo.py            scripted Tim Hortons simulation
tests/                 pytest suite
```
