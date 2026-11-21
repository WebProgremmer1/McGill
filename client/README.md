# What’s Next? frontend demo

React + Vite with the existing Oxlint setup. The default demo uses fictional journeys from FastAPI on port 8000. Vite proxies requests under `/api` to that server.

```sh
cd client
npm install
npm run dev
```

Open the URL printed by Vite (normally `http://localhost:5173`).

## Presenting

Open `/signup` in two browser windows on the same Vite origin. Under **Try the demo**, choose **I’m signing up for myself** in one window to open Today at `/`, and **I’m a caregiver** in the other to open the Care dashboard at `/manage`. The URL is each window’s role, so reloading or changing one window does not affect the other. The cards create no account or session. Until the auth backend exists, these screens use neutral headings and show no person’s name. Replay and reset are presenter tools at `http://127.0.0.1:8000/docs`, or:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/demo/reset
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/demo/run
```

Reset clears backend journeys, reminders, and help requests. The replay gives Today a check-in. Both screens poll every two seconds and follow the newest active journey.

## Destinations

Today offers only places with a usable route. From Home that is **Go to Tim Hortons**, the backend’s one predefined route. **Go home** appears once the person is away from Home and follows the known route back. The backend has no street names, so directions are approximate and start from the last known location. Today and the Care dashboard embed the backend map through Vite’s `/viewer` proxy.

## Sign-in and care circles

`/onboarding` calls the agreed `GET /api/auth/google/start` route and reports that Google sign-in is unavailable until it exists. It never fakes a successful sign-in. Run `npm run dev:onboarding` to test the screens after sign-in with a labeled fictional session from `/test-session`, using invite code `ELLIS-CARE` or the reminders-only `ELLIS-VIEW`. Names, relationships, photos, phone numbers, and dashboard access come from the account and circle data. The normal `npm run dev` demo stays open and has no sign-in. See [the auth handoff](docs/AUTH_HANDOFF.md) for the backend work required before real use.

## Reminders and portraits

In the open demo, **Send reminder** stores a closed demo record through FastAPI’s journeys API because no reminders route exists yet. Both dashboards read it by polling, and it has no sender. With the account API, the backend records the signed-in sender. A portrait and relationship appear only when that person’s profile includes them. Otherwise, initials and the name are shown.

## Help and calling

**Get help**, or **Ask [caregiver] for help** once a caregiver is linked, creates a backend help request for the Care dashboard. It does not call or notify anyone. A **Call** action appears only when the backend returns that person’s phone number. No phone number is stored in source.

## Mock walkthrough

1. Open `/?mode=mock` in one tab for the Today board.
2. Open `/manage?mode=mock` in a second tab in the same browser profile and on the same origin (same hostname and port).
3. On the Care dashboard, select **Reset demo**, then **Simulate off-route walk**.
4. Return to Today. The inline check-in asks **“Still heading to Maple Market?”**. A polite live region announces it once per check-in per mounted Today board.
5. Use Tab / Shift+Tab to reach **Keep going**, **Show directions**, or **Get help**, then Enter / Space to activate. Focus has a visible outline and buttons are at least 68px tall.
6. **Keep going** displays reassurance. **Show directions** expands fictional walking instructions. **Get help** creates a simulated request visible immediately on the Care dashboard. The choices remain available; repeat clicks preserve the existing request.
7. **Reset demo** clears the check-in and request across both tabs so you can repeat. Refreshing preserves the demo until reset.

Browser local storage must be enabled. Tabs in different profiles, ports, or hostnames do not share state. If storage is unavailable, an error banner explains the limitation.

## Data boundary

`src/data/journeyApi.js` handles FastAPI requests and remembers the selected backend journey ID across tabs. Journey details, check-ins, and alerts come from FastAPI. The fallback uses `src/data/demoStore.js` with its existing local storage and cross-tab subscriptions.

The sample date is fixed to Friday, November 20; it is not a live clock. For static production hosting, configure history fallback to `index.html` for `/manage`.

```sh
npm run lint
npm test
npm run build
npm run preview
```
