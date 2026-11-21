# What’s Next? frontend demo

React + Vite with the existing Oxlint setup. All profiles, schedules, routes, and requests are fictional. No backend, tracking, telephone calls, or notifications are used.

```sh
cd client
npm install
npm run dev
```

Open the URL printed by Vite (normally `http://localhost:5173`).

## Two-tab walkthrough

1. Open `/` in one tab for Eleanor’s Today board.
2. Open `/manage` in a second tab, in the same browser profile and on the same origin (same hostname and port).
3. On Family, select **Reset demo**, then **Simulate off-route walk**.
4. Return to Today. The inline check-in asks **“Still heading to the grocery store?”**. A polite live region announces it once per check-in per mounted Today board. There is no focus movement, modal, sound, or automatic navigation.
5. Use Tab / Shift+Tab to reach **Keep going**, **Show directions**, or **Ask Maya for help**, then Enter / Space to activate. Focus has a visible outline and buttons are at least 68px tall.
6. **Keep going** displays reassurance. **Show directions** expands fictional walking instructions. **Ask Maya for help** creates a simulated contact request visible immediately on Family. The choices remain available; repeat Ask Maya for help clicks preserve the existing request.
7. **Reset demo** clears the check-in and request across both tabs so you can repeat. Refreshing preserves the demo until reset.

Browser local storage must be enabled. Tabs in different profiles, ports, or hostnames do not share state. If storage is unavailable, an error banner explains the limitation.

## Data boundary

`src/data/demoStore.js` owns all fictional data, persistence, and mutations. Components consume its `demoData` and `demoStore` interface with React’s `useSyncExternalStore`. Same-tab subscriptions and cross-tab storage events keep views current. Actions read the latest stored state before writing. Replace this module with a FastAPI adapter and polling or a push subscription later; the UI has no direct storage access. Local storage is for demo data only and is not a production data store.

The sample date is fixed to Friday, November 20; it is not a live clock. For static production hosting, configure history fallback to `index.html` for `/manage`.

```sh
npm run lint
npm test
npm run build
npm run preview
```
