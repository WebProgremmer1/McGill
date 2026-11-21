# Safety Backend

Follows someone on a walk (for example, Home to Tim Hortons). It gives the walk a
risk score from 0 to 100 and gets a caregiver involved if the score gets high.

Hackathon prototype with made-up data. Not a medical tool.

## Run it

```
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Then open one of these:

* http://localhost:8000: **live Google map**. Pick any start and destination in
  Montreal and the backend gets a real walking route from Google. Then either **walk it yourself**
  (each click on the map moves her and counts as 1 minute; "Stay here" waits 1 minute in place)
  or play a scenario (normal walk, parallel street, wrong way, loops, leaving the safe zone, lost and stopped).
  A log shows every GPS point: how far off the route it was, the score, and which rules added points.
* http://localhost:8000/docs: every endpoint.

The live map needs `GOOGLE_MAPS_API_KEY` in `.env`, with **Routes API**, **Maps JavaScript API**
and **Places API** turned on for that key in Google Cloud. The page loads the key in the browser,
so restrict it to `http://localhost:8000/*` (or put a separate browser key in `GOOGLE_MAPS_BROWSER_KEY`).

Other commands:

```
python -m pytest          # run the tests
python -m app.demo        # print the scripted demo walk in the terminal
```

---

## The rules (heuristics)

When the phone sends a new GPS point, the score is **worked out again from the
whole walk so far**. Points are not carried over from the last update, so if she
gets back on the route the off-route points disappear.

There are five rules. The final score is all of them added together (max 100).

### Rule 1: Off route

The rule has **two parts that are added together**. A short or small mistake
gets a few points. Being far away, or being off route for a long time, gets
a lot.

**Part A: how far from the route is she right now?**

| Distance from the route | Name | Points |
|---|---|---|
| 0 to 50 m | On route (GPS wobble, other side of the street) | 0 |
| 50 to 150 m | A little off route | 10 |
| 150 to 300 m | Off route | 25 |
| More than 300 m | Far off route | 40 |

**Part B: how long has she been off route?**

* +2 points for every minute since she first went more than 50 m off the route.
* Maximum 40 points.

Examples:

| Situation | Part A | Part B | Off-route points |
|---|---|---|---|
| 100 m off, just happened | 10 | 0 | **10** (low) |
| 100 m off for 10 minutes | 10 | 20 | **30** (medium) |
| 400 m off, just happened | 40 | 0 | **40** (medium) |
| 400 m off for 10 minutes | 40 | 20 | **60** (high) |
| 200 m off for 20 minutes | 25 | 40 | **65** (high) |

### Rule 2: Standing still

* "Standing still" means staying within 25 m of the same spot.
* The first 2 minutes are free, because people stop at crosswalks.
* After that: +3 points per minute.
* Maximum 25 points.
* Does not count when she is at the destination (waiting at Tim Hortons is fine).

Example: standing still for 7 minutes = (7 - 2) x 3 = **15 points**.

### Rule 3: Going in loops

* We look at the spot she is standing on now (a 30 m circle).
* We count how many separate times she has been in that circle. Arriving,
  leaving and arriving again counts as 2 visits, which is 1 return.
* +15 points per return.
* Maximum 30 points.

Example: she walks around the same block twice and is back at the same corner,
so that is 1 return and **15 points**.

### Rule 4: Left a safe zone

* A safe zone is a circle around a place, for example 75 m around Tim Hortons.
  The frontend sends the zones when the journey starts.
* If she was inside a safe zone earlier, and now she is outside every safe zone,
  she gets **15 points**.
* Zones around the start (Home) never count, because leaving home is the point of the walk.
* If she walks back into the zone, the 15 points go away.

### Rule 5: Taking too long

This looks at the **whole trip**, not just where she is right now. It catches
someone who stays on the route but is very slow, or keeps stopping for short breaks.

* The expected walk time comes from `expected_arrival - started_at`, which is sent
  when the journey starts. The live map uses Google's walking time for the route.
* She gets **1.5 times** the expected time for free, because older people walk
  slower than maps assume.
* After that: **+2 points per minute**, up to **30**.
* Once she has reached the destination (within 50 m), this rule stops counting.

Example: a 10-minute walk is free until minute 15. At minute 20 she gets
(20 - 15) x 2 = **10 points**. At minute 30 or later she gets the maximum, **30 points**.

### What the score does

| Score | Level | What happens |
|---|---|---|
| 0 to 29 | Low | Nothing, keep watching |
| 30 to 59 | Medium | Ask her "Are you okay?" on the phone (at most once every 10 minutes) |
| 60 to 100 | High | Send one alert to the caregiver |
| Help button | | Send an urgent alert to the caregiver right away |

All of the numbers are in plain sight in [app/risk.py](app/risk.py). To change
a rule, change the number there and in this table.

---

## How metres are worked out from GPS

The phone gives us **latitude** (degrees north) and **longitude** (degrees east).
To measure in metres, we convert the difference between two points into metres
on a flat grid. This is in [app/geo.py](app/geo.py).

1. **North-south:** 1 degree of latitude is always about **111,320 m**.
   So `north_m = (lat2 - lat1) x 111,320`.
2. **East-west:** lines of longitude get closer together as you move away from
   the equator, so 1 degree of longitude is shorter. Multiply by `cos(latitude)`.
   In Montreal (latitude 45.5°), cos(45.5°) is about 0.70, so 1 degree is about **78,000 m**.
   So `east_m = (lon2 - lon1) x 111,320 x cos(lat1)`.
3. **Distance:** now it is a right-angled triangle, so use Pythagoras:
   `distance = sqrt(east_m² + north_m²)`.

Treating the city as flat is accurate to well under a metre over a few km.

**Distance to the route.** The route is a list of points joined by straight
lines (segments). For each segment we find the closest spot on it to her (a
projection, like in linear algebra). The distance to the route is the
smallest of those distances.

```
   route:  A ----------X---------- B
                       |
                       |  <- distance to this segment
                       |
                      her
```

If the closest spot would be past the end of a segment, we use the end point instead.

---

## What each file does

| File | What it does |
|---|---|
| [app/risk.py](app/risk.py) | **The five rules.** Takes a journey and returns the score, level and reasons. |
| [app/geo.py](app/geo.py) | GPS maths: degrees to metres, distance between points, distance to the route. |
| [app/service.py](app/service.py) | Stores journeys in memory. On every GPS point it runs `risk.assess()`, then creates a check-in (medium) or a caregiver alert (high), and avoids sending duplicates. |
| [app/main.py](app/main.py) | The web API (FastAPI): every URL the frontend can call, e.g. `POST /api/journeys/{id}/location`. Also `GET /api/maps-config` (Google key for the live map) and `POST /api/expected-route` (look up a walking route). |
| [app/models.py](app/models.py) | The shape of the data (Pydantic): Journey, TrackPoint, SafeZone, RiskAssessment, CheckIn, Alert. Checks input such as "latitude must be between -90 and 90". |
| [app/routes_provider.py](app/routes_provider.py) | Gets the walking route once, when a journey starts. Order: the frontend's route, then the built-in demo route, then Google Routes, then a straight line if all else fails. |
| [app/demo.py](app/demo.py) | A pretend walk that gets lost, put through the real rules. Used by the "Play demo" button. |
| [app/config.py](app/config.py) | Reads settings (Google key, allowed frontend URLs) from `.env`. |
| [app/errors.py](app/errors.py) | Makes every error reply look the same. |
| [viewer/live-map.html](viewer/live-map.html) | The live Google map page. Builds pretend walks along a real route and sends them to the API one GPS point at a time. Shows the score, the phone check-in and the caregiver alerts. || [tests/](tests/) | Automated tests (pytest) for every rule and endpoint. |
| [API_CONTRACT.md](API_CONTRACT.md) | Request and response examples for the frontend team. |
| `.env` | Your Google key. Never uploaded to GitHub. Copy `.env.example` to make one. |

## What happens on one GPS update

```
phone sends {latitude, longitude, timestamp}
  -> main.py       POST /api/journeys/{id}/location
  -> service.py    adds the point to the journey's track
  -> risk.py       off_route + standing_still + going_in_loops + left_safe_zone + taking_too_long = score
  -> service.py    medium? make a check-in.  high? make a caregiver alert.
  -> reply with the score, the reasons, and any check-in or alert created
```
