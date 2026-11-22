# Prompt: apply the "Golden Hour" front-end design to the `google-integration` branch

Copy everything below this line and give it to the agent (or developer) working on `google-integration`.

---

You are working in the McGill repo (GitHub `WebProgremmer1/McGill`), branch **`google-integration`**. The client is React + Vite in `client/`, and the FastAPI backend (with the map pages in `backend/viewer/`) is in `backend/`.

Apply the "Golden Hour" redesign described below. It was built and tested on the `ui` branch in four commits, on top of `google-integration` commit `dc350a1`:

| Commit | What it does |
|---|---|
| `9cdeeff` | Golden Hour colors, pill buttons, small pointer effects, warmer map card and map pages |
| `afb58e5` | App-style layout for both dashboards (app bar, hero cards, two columns, timeline, list rows) |
| `bcd66fb` | Demo: click or drag on the dashboard map to move the walker's location |
| `b22b830` | Live map page: typing places works again (new backend search), Golden Hour restyle with purple |

## Fastest path (preferred)

If `google-integration` is still at `dc350a1` (or has only unrelated changes), bring the commits over with git instead of re-typing anything:

```bash
git fetch origin
git switch google-integration
git merge --ff-only origin/ui        # works when google-integration is still dc350a1
# otherwise:
git cherry-pick 9cdeeff afb58e5 bcd66fb b22b830
```

Then check it: `cd client && npm install && npm run lint && npm test && npm run build`, and `cd backend && pytest`. Only fall back to the manual spec below if the cherry-pick conflicts.

## Ground rules

- **Change the look, not the behavior.** Keep every existing screen, text, route, permission check, focus handling and live region. The only new behaviors are the ones listed under "Behavior changes".
- **Accessibility stays at WCAG AA:** text contrast ≥ 4.5:1, visible focus rings, buttons at least 44–48px tall, and every animation switched off under `prefers-reduced-motion: reduce`.
- **Leave alone:** help and error reds (`#8a2f1d`, `#6f2415`, `#842e23`, `#a24b3d`, `#fff0eb`, `#fff3e4`, `#85501d`) stay as they are, so urgent actions still look different from the rose main button. The map's risk colors (green / amber / red) also stay.

## 1. Color palette (Golden Hour)

| Token | Hex | Role |
|---|---|---|
| `--gh-cream` | `#FFF6E8` | Page background |
| `--gh-sand` | `#FDE9C4` | Tinted panels, icon tiles |
| `--gh-apricot` | `#FFD9A0` | Care hero card, role-picker background |
| `--gh-ink` | `#3B2B45` | Main text (12.1:1 on cream), focus ring |
| `--gh-dusk` | `#5B4A6E` | Secondary text (7.4:1), form borders, disabled buttons |
| `--gh-rose` | `#A8435A` | Main buttons with white text (5.8:1), links, icons |
| `--gh-rose-deep` | `#8E3549` | Hover and pressed state of rose |
| `--gh-marigold` | `#F0B04F` | Highlights, check-in border, chips (ink text only) |
| `--gh-pumpkin` | `#E08A3C` | Decoration only |
| `--gh-violet` | `#8F6D97` | Decoration only (fails as text) |
| `--gh-plum` | `#6E5683` | Purple accent: hero gradients, selection, the "?" in the logo |
| `--gh-sage` | `#6B7F6A` | Safe zones and the "live" dot; never text |
| `--gh-peri` | `#7B8FD1` | Illustration sky only |
| `--gh-line` | `#EDD3AA` | Borders and dividers |
| `--gh-focus` | `#3B2B45` | Focus outline |

### 1a. Define the tokens: prepend this to `client/src/index.css`

The same diff also points `:root` `color`, `background` and `--secondary-text` at the tokens:

```diff
diff --git a/client/src/index.css b/client/src/index.css
index 5dd1e53..585ba63 100644
--- a/client/src/index.css
+++ b/client/src/index.css
@@ -1,10 +1,21 @@
-:root { --secondary-text: #435849; font-family: 'Segoe UI', Arial, sans-serif; color: #263b35; background: #f8faf8; font-synthesis: none; text-rendering: optimizeLegibility; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; font-size: 100%; }
+:root {
+  /* Golden Hour theme. Text pairings meet WCAG AA:
+     ink on cream 12.1:1, dusk on cream 7.4:1, white on rose 5.8:1, rose on white 5.8:1. */
+  --gh-cream: #FFF6E8; --gh-sand: #FDE9C4; --gh-apricot: #FFD9A0;
+  --gh-ink: #3B2B45; --gh-dusk: #5B4A6E;
+  --gh-rose: #A8435A; --gh-rose-deep: #8E3549;
+  --gh-marigold: #F0B04F; --gh-pumpkin: #E08A3C;
+  --gh-violet: #8F6D97; --gh-plum: #6E5683;
+  --gh-sage: #6B7F6A; --gh-peri: #7B8FD1;
+  --gh-line: #EDD3AA; --gh-focus: #3B2B45;
+}
+:root { --secondary-text: var(--gh-dusk); font-family: 'Segoe UI', Arial, sans-serif; color: var(--gh-ink); background: var(--gh-cream); font-synthesis: none; text-rendering: optimizeLegibility; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; font-size: 100%; }
 * { box-sizing: border-box; }
 body { margin: 0; min-width: 320px; }
 button, a { -webkit-tap-highlight-color: transparent; touch-action: manipulation; min-width: 44px; min-height: 44px; }
 button { font: inherit; cursor: pointer; }
 button:disabled { cursor: default; opacity: .65; }
 a { color: inherit; }
-button:focus-visible, a:focus-visible { outline: 3px solid #854510; outline-offset: 5px; }
+button:focus-visible, a:focus-visible { outline: 3px solid var(--gh-focus); outline-offset: 5px; }
 h1, h2, h3, p { margin: 0; }
 .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; border: 0; }
```

### 1b. Swap every hard-coded green or beige for a token

Apply this in `client/src/App.css`, `client/src/SignUp.css` and `client/src/DemoRolePicker.css`. Replace each 6-digit hex below with its token; leave the reds listed under "Ground rules" alone.

| Old colors | New token |
|---|---|
| `#263b35 #12281b #1f3a2a #334b3e #2f4737 #38503e #294b34 #31543b` | `var(--gh-ink)` |
| `#435849 #4e6854 #426348 #496c42 #607154 #647b5a #6d6046 #725639 #795a22 #5f3209 #526557 #5d7565` | `var(--gh-dusk)` |
| `#315b42 #27503a #467757 #285c42 #47745a` | `var(--gh-rose)` |
| `#224630` | `var(--gh-rose-deep)` |
| `#6c8c56` | `var(--gh-plum)` |
| `#8fa396` | `var(--gh-violet)` |
| `#854510` (focus outlines) | `var(--gh-focus)` |
| `#e2e9e4 #d9e2da #dfe6dd #e1e7df #e0e7df #dfe6de #cfd9d1 #ccd8c5 #d7e1d2 #dce7d5 #e4dcc6 #e5dfcf #d8cfb8` | `var(--gh-line)` |
| `#e9f0e6 #f1f5ee #eef2e9 #edf2e9 #e9ede6 #e6ebe2 #eef1eb #e8e9d9 #f5e9ce #f0eddf` | `var(--gh-sand)` |
| `#f8faf8 #fffdf7 #fbf6ea #fffaf0 #fff8e9` | `var(--gh-cream)` |
| `#eedfce #f2b8a2` | `var(--gh-apricot)` |
| `#d9ba7c #dfc997 #c2a56e` | `var(--gh-marigold)` |
| `#60844e` | `var(--gh-sage)` |

Also:
- In `App.css`, set `.check-in { background: #fff; }` so the check-in card stands out from the cream page.
- In `client/index.html`, change `<meta name="theme-color">` from `#315b42` to `#A8435A`.
- In `client/public/whats-next.svg`, change the fill `#315b42` to `#A8435A`.
- In `client/index.html`, load the font: `https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400;700&display=swap` (with preconnects to `fonts.googleapis.com` and `fonts.gstatic.com`).

## 2. Pill buttons and gentle interactions: new `client/src/theme.css` and `client/src/theme.js`

Load them in `client/src/main.jsx` **after** `App.jsx`, so they come last in the stylesheet order:

```diff
diff --git a/client/src/main.jsx b/client/src/main.jsx
index b9a1a6d..aef5e39 100644
--- a/client/src/main.jsx
+++ b/client/src/main.jsx
@@ -2,6 +2,9 @@ import { StrictMode } from 'react'
 import { createRoot } from 'react-dom/client'
 import './index.css'
 import App from './App.jsx'
+import './theme.css'
+import './app-ui.css'
+import './theme.js'
 
 createRoot(document.getElementById('root')).render(
   <StrictMode>
```

`client/src/theme.css`:

```css
/* Golden Hour: button shapes and small interactive touches.
   Loaded after the page styles. Motion is off when "reduce motion" is on. */

/* ---------- Buttons ---------- */
.button, .get-help, .signup-submit {
  position: relative; overflow: hidden; isolation: isolate;
  border-radius: 999px;
  transition: background-color .25s ease, box-shadow .25s ease, transform .15s ease;
}
.primary, .signup-submit {
  border: 1px solid var(--gh-rose-deep);
  box-shadow: 0 4px 0 var(--gh-rose-deep), 0 8px 18px rgba(142, 53, 73, .22);
}
.primary:hover:not([aria-disabled="true"]), .signup-submit:hover { background-color: var(--gh-rose-deep); }
.primary:active:not([aria-disabled="true"]), .signup-submit:active {
  transform: translateY(3px);
  box-shadow: 0 1px 0 var(--gh-rose-deep), 0 4px 10px rgba(142, 53, 73, .2);
}
.secondary { border: 2px solid var(--gh-rose); color: var(--gh-rose-deep); background-color: var(--gh-cream); }
.secondary:hover { background-color: var(--gh-sand); }
.get-help, .button.help-call { box-shadow: 0 4px 0 #6f2415; }
.get-help:active, .button.help-call:active { transform: translateY(3px); box-shadow: 0 1px 0 #6f2415; }
.text-button, .directions-link { text-decoration-color: var(--gh-rose); text-decoration-thickness: 2px; }

/* Warm light that follows the pointer across a button or card. */
.primary, .get-help, .signup-submit, .demo-role-card {
  background-image: radial-gradient(circle at var(--mx, 50%) var(--my, 50%), rgba(255, 246, 232, var(--glow, 0)), transparent 65%);
}
.primary:hover:not([aria-disabled="true"]), .get-help:hover, .signup-submit:hover, .demo-role-card:hover {
  --glow: .28;
  /* Repeated here because the page styles set hover colors with the background shorthand. */
  background-image: radial-gradient(circle at var(--mx, 50%) var(--my, 50%), rgba(255, 246, 232, var(--glow)), transparent 65%);
}

/* Soft ring where a button is pressed. */
.gh-ripple {
  position: absolute; z-index: -1; width: 12px; height: 12px; margin: -6px 0 0 -6px; border-radius: 50%;
  background: rgba(255, 246, 232, .55); pointer-events: none; animation: gh-ripple .7s ease-out forwards;
}
.secondary .gh-ripple, .demo-role-card .gh-ripple { background: rgba(240, 176, 79, .45); }
@keyframes gh-ripple { to { transform: scale(30); opacity: 0; } }

/* ---------- Role picker ---------- */
.role-picker { background: var(--gh-apricot); }
/* A sunset glow that drifts after the pointer. */
.role-picker::after {
  content: ''; position: fixed; inset: 0; z-index: -1; pointer-events: none;
  background: radial-gradient(420px circle at var(--px, 70%) var(--py, 45%), rgba(255, 228, 160, .45), transparent 70%);
  transition: background-position .3s ease;
}
.demo-role-card {
  border-color: var(--gh-rose-deep);
  color: var(--gh-ink);
  transform: perspective(900px) rotateX(var(--rx, 0deg)) rotateY(var(--ry, 0deg));
  transition: transform .35s ease, box-shadow .35s ease, background-color .35s ease;
}
.demo-role-card:hover { transform: perspective(900px) rotateX(var(--rx, 0deg)) rotateY(var(--ry, 0deg)) translateY(-6px); box-shadow: 0 18px 40px rgba(59, 43, 69, .28); }
.demo-role-card-icon { color: var(--gh-rose); transition: transform .4s ease; }
.demo-role-card:hover .demo-role-card-icon { transform: scale(1.08) rotate(-4deg); }
.demo-role-card-opens { color: var(--gh-rose-deep); }
.demo-role-card:focus-visible { outline-color: var(--gh-ink); }

/* ---------- Check-in: a gentle glow so it is noticed ---------- */
.check-in { animation: gh-checkin-glow 3.5s ease-in-out infinite; }
@keyframes gh-checkin-glow {
  0%, 100% { box-shadow: 0 0 0 0 rgba(240, 176, 79, 0); }
  50% { box-shadow: 0 0 0 8px rgba(240, 176, 79, .35); }
}

/* Choice cards and radio-style options settle in when picked. */
.choice:has(input:checked), .signup-role input:checked + .signup-role-card { animation: gh-pick .35s ease-out; }
@keyframes gh-pick { 0% { transform: scale(.97); } 60% { transform: scale(1.015); } 100% { transform: none; } }

/* Live dot breathes like the sun. */
.status-dot { box-shadow: 0 0 0 0 rgba(107, 127, 106, .5); animation: gh-dot 2.4s ease-in-out infinite; }
@keyframes gh-dot { 50% { box-shadow: 0 0 0 6px rgba(107, 127, 106, 0); } }

@media (prefers-reduced-motion: reduce) {
  .check-in, .status-dot, .choice:has(input:checked), .signup-role input:checked + .signup-role-card, .gh-ripple { animation: none; }
  .gh-ripple { display: none; }
  .button, .get-help, .signup-submit, .demo-role-card, .demo-role-card-icon { transition: none; }
  .demo-role-card, .demo-role-card:hover { transform: none; }
  .demo-role-card:hover .demo-role-card-icon { transform: none; }
}
@media (forced-colors: active) {
  .primary, .get-help, .signup-submit, .demo-role-card { background-image: none; }
  .role-picker::after { display: none; }
}
```

`client/src/theme.js` (one set of document-level listeners; does nothing when "reduce motion" is on):

```js
// Small pointer effects for the Golden Hour theme. One set of document listeners,
// so they work for buttons React adds later. Skipped when "reduce motion" is on.
const INTERACTIVE = '.primary, .secondary, .get-help, .signup-submit, .demo-role-card'
const TILT = '.demo-role-card'
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

function onMove(event) {
  if (reduceMotion.matches) return
  const picker = document.querySelector('.role-picker')
  if (picker) {
    picker.style.setProperty('--px', `${event.clientX}px`)
    picker.style.setProperty('--py', `${event.clientY}px`)
  }
  const el = event.target.closest?.(INTERACTIVE)
  if (!el) return
  const box = el.getBoundingClientRect()
  const x = (event.clientX - box.left) / box.width
  const y = (event.clientY - box.top) / box.height
  el.style.setProperty('--mx', `${x * 100}%`)
  el.style.setProperty('--my', `${y * 100}%`)
  if (el.matches(TILT)) {
    el.style.setProperty('--ry', `${(x - .5) * 6}deg`)
    el.style.setProperty('--rx', `${(.5 - y) * 6}deg`)
  }
}

function onLeave(event) {
  const el = event.target.closest?.(TILT)
  if (el && !el.contains(event.relatedTarget)) {
    el.style.removeProperty('--rx')
    el.style.removeProperty('--ry')
  }
}

function onDown(event) {
  if (reduceMotion.matches) return
  const el = event.target.closest?.(INTERACTIVE)
  if (!el || el.getAttribute('aria-disabled') === 'true') return
  const box = el.getBoundingClientRect()
  const ring = document.createElement('span')
  ring.className = 'gh-ripple'
  ring.setAttribute('aria-hidden', 'true')
  ring.style.left = `${event.clientX - box.left}px`
  ring.style.top = `${event.clientY - box.top}px`
  ring.addEventListener('animationend', () => ring.remove())
  el.append(ring)
}

document.addEventListener('pointermove', onMove, { passive: true })
document.addEventListener('pointerout', onLeave, { passive: true })
document.addEventListener('pointerdown', onDown, { passive: true })
```

## 3. App-style layout: new `client/src/app-ui.css` plus small markup changes

These are patterns used by real apps:
- a sticky app bar;
- one colored hero card per screen;
- white cards whose header is an icon in a rounded tile plus a title;
- settings-style list rows;
- a dotted activity timeline;
- status chips;
- numbered direction steps;
- dashed empty states;
- one very readable typeface.

`client/src/app-ui.css` (loaded last, see `main.jsx` above):

```css
/* App layer: makes the dashboards read like a real mobile/desktop app.
   Patterns: sticky app bar, one colored hero card per screen, white cards with an
   icon-tile header, settings-style list rows, a dotted activity timeline, status chips.
   Loaded after App.css and theme.css. */

:root {
  --ui-font: 'Atkinson Hyperlegible Next', 'Atkinson Hyperlegible', 'Segoe UI', system-ui, sans-serif;
  --ui-radius: 22px;
  --ui-radius-sm: 14px;
  --ui-shadow: 0 1px 2px rgba(59, 43, 69, .05), 0 8px 24px rgba(110, 86, 131, .09);
  --ui-shadow-lift: 0 2px 4px rgba(59, 43, 69, .06), 0 16px 36px rgba(110, 86, 131, .16);
  --ui-gap: 20px;
  font-family: var(--ui-font);
}
body { background: var(--gh-cream); }
.page { padding: 28px 24px 64px; min-height: auto; }

/* ---------- App bar ---------- */
.site-header.app-bar {
  position: sticky; top: 0; z-index: 20;
  display: flex; align-items: center; gap: 14px;
  min-height: 76px; padding: 12px max(20px, calc((100vw - 76rem) / 2));
  border-bottom: 1px solid rgba(237, 211, 170, .7);
  background: rgba(255, 246, 232, .86);
  -webkit-backdrop-filter: saturate(1.4) blur(14px); backdrop-filter: saturate(1.4) blur(14px);
}
.app-mark {
  flex: none; display: grid; place-items: center; width: 46px; height: 46px; border-radius: 14px;
  background: linear-gradient(145deg, var(--gh-rose), var(--gh-plum)); color: #fff;
  box-shadow: 0 6px 16px rgba(142, 53, 73, .28);
}
.app-mark svg { width: 26px; height: 26px; stroke-width: 2; }
.app-title { min-width: 0; flex: 1; display: grid; gap: 2px; }
.app-bar .person-name { grid-area: auto; margin: 0; display: block; text-align: left; font-size: clamp(1.375rem, 1.1rem + 1vw, 1.75rem); font-weight: 700; letter-spacing: -.3px; line-height: 1.15; white-space: normal; overflow-wrap: anywhere; }
.app-subtitle { color: var(--gh-dusk); font-size: 1rem; line-height: 1.3; }
.app-bar .header-action { flex: none; }

/* ---------- Cards ---------- */
.today-view .today-section, .family-view .panel, .family-view .panel:not(.has-request, .demo-controls) {
  padding: 22px; border: 1px solid rgba(237, 211, 170, .9); border-radius: var(--ui-radius); background: #fff; box-shadow: var(--ui-shadow);
}
.icon-heading { gap: 12px; font-size: 1.25rem; font-weight: 700; letter-spacing: -.2px; }
.family-view .panel h2, .today-section h2 { font-size: 1.3rem; font-weight: 700; }
.icon-heading svg {
  width: 40px; height: 40px; padding: 8px; border-radius: 12px; background: var(--gh-sand); color: var(--gh-rose); stroke-width: 2;
}

/* ---------- Patient screen ---------- */
.today-view { max-width: 72rem; display: grid; gap: var(--ui-gap); font-size: 1.1875rem; }
.today-side { display: grid; gap: var(--ui-gap); align-content: start; min-width: 0; }
@media (min-width: 980px) {
  .today-view { grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); align-items: start; }
  .today-view > .check-in { grid-column: 1 / -1; }
  .today-view > .today-section { grid-column: 1; grid-row: auto; }
  .today-view > .today-side { grid-column: 2; position: sticky; top: 100px; }
  .today-view:has(> .check-in) > .today-side, .today-view:has(> .check-in) > .today-section { grid-row: 2; }
  .today-view:not(:has(> .check-in)) > .today-side, .today-view:not(:has(> .check-in)) > .today-section { grid-row: 1; }
}

/* Hero: the day's reminders, in the app's one colored card. */
.today-view .message-card {
  position: relative; overflow: hidden; isolation: isolate;
  border: 0; background: linear-gradient(150deg, var(--gh-rose) 0%, #8C4A6C 55%, var(--gh-plum) 100%);
  box-shadow: 0 18px 40px rgba(110, 86, 131, .3);
}
.today-view .message-card::after {
  content: ''; position: absolute; z-index: -1; right: -70px; top: -70px; width: 220px; height: 220px; border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 228, 160, .55), rgba(255, 228, 160, 0) 70%);
}
.message-card .icon-heading svg { background: rgba(255, 255, 255, .18); color: #fff; }
.message-card .reminder-message { font-size: 1.3rem; line-height: 1.45; }

/* Quick actions */
.patient-actions { gap: 12px; padding: 16px; border-radius: var(--ui-radius); background: #fff; border: 1px solid rgba(237, 211, 170, .9); box-shadow: var(--ui-shadow); }
.today-confirmation-wrap:not(:has(:not(:empty))) { display: none; }
.today-confirmation:not(:empty), .email-status:not(:empty) { border-radius: var(--ui-radius-sm); }

/* Check-in: an attention banner at the top of the screen. */
.today-view .check-in {
  display: grid; gap: 4px; padding: 24px; border: 2px solid var(--gh-marigold); border-radius: var(--ui-radius);
  background: linear-gradient(180deg, #FFF9EE, #fff); box-shadow: var(--ui-shadow-lift);
}
.today-view .check-in h2 { display: flex; align-items: center; gap: 14px; }
.today-view .check-in h2::before {
  content: ''; flex: none; width: 14px; height: 14px; border-radius: 50%; background: var(--gh-marigold);
  box-shadow: 0 0 0 6px rgba(240, 176, 79, .3);
}
.today-view .check-in-actions { margin-top: 16px; }

/* Destinations as tappable list rows with a chevron. */
.destination-list { gap: 0; border: 1px solid rgba(237, 211, 170, .9); border-radius: var(--ui-radius-sm); overflow: hidden; }
.destination-list li + li { border-top: 1px solid rgba(237, 211, 170, .9); }
.today-view .button.destination-button {
  min-height: 76px; padding: 12px 18px; border: 0; border-radius: 0; background: #fff; box-shadow: none; font-size: 1.375rem;
}
.today-view .button.destination-button:hover { background: var(--gh-cream); }
.today-view .button.destination-button svg { width: 48px; height: 48px; padding: 10px; border-radius: 14px; background: var(--gh-sand); }
.today-view .button.destination-button::after {
  content: ''; margin-left: auto; flex: none; width: 12px; height: 12px; border-top: 3px solid var(--gh-dusk); border-right: 3px solid var(--gh-dusk);
  border-radius: 2px; transform: rotate(45deg);
}

/* Directions as a numbered stepper. */
.direction-steps { list-style: none; counter-reset: step; padding: 0; gap: 0; font-size: 1.125rem; }
.direction-steps li { position: relative; counter-increment: step; padding: 6px 0 18px 48px; }
.direction-steps li::before {
  content: counter(step); position: absolute; left: 0; top: 2px; display: grid; place-items: center; width: 32px; height: 32px;
  border-radius: 50%; background: var(--gh-sand); color: var(--gh-ink); font-weight: 700; font-size: 1rem;
}
.direction-steps li:not(:last-child)::after {
  content: ''; position: absolute; left: 15px; top: 38px; bottom: 2px; border-left: 2px dotted var(--gh-marigold);
}
.directions-note { color: var(--gh-dusk); font-size: 1rem; }

/* ---------- Care screen ---------- */
.family-view {
  max-width: 76rem; display: grid; gap: var(--ui-gap); font-size: 1.125rem;
  grid-template-columns: minmax(0, 1fr);
}
.care-main, .care-side { display: grid; gap: var(--ui-gap); align-content: start; min-width: 0; }
@media (min-width: 980px) {
  .family-view { grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); align-items: start; }
  .family-view > .caring-card { grid-column: 1 / -1; }
}
.care-side .care-top-row { grid-template-columns: minmax(0, 1fr); gap: var(--ui-gap); }

/* Hero: who you are caring for. */
.family-view .caring-card {
  position: relative; overflow: hidden; isolation: isolate; gap: 18px; padding: 24px 26px; border: 0; border-radius: var(--ui-radius);
  background: linear-gradient(120deg, var(--gh-apricot), var(--gh-sand) 60%, #FFF0DA); box-shadow: var(--ui-shadow);
}
.family-view .caring-card::after {
  content: ''; position: absolute; z-index: -1; right: -40px; bottom: -90px; width: 260px; height: 180px; border-radius: 50% 50% 0 0;
  background: rgba(143, 109, 151, .14);
}
.caring-card .contact-photo { width: 64px; height: 64px; box-shadow: 0 0 0 4px #fff; }
.caring-card h2 { font-size: 1.625rem; font-weight: 700; }

/* Help: an alert card that is impossible to miss when active. */
.family-view .help-panel.has-request { border: 2px solid #8a2f1d; border-left-width: 2px; background: #FFF3EC; box-shadow: 0 12px 30px rgba(138, 47, 29, .16); }
.family-view .help-panel.has-request h2 svg { background: #8a2f1d; color: #fff; }
.family-view .help-panel:not(.has-request) p { color: var(--gh-dusk); }

/* Activity timeline */
.care-feed-walk {
  display: inline-flex; align-items: center; gap: 8px; justify-self: start; width: fit-content; margin-top: 12px; padding: 6px 14px;
  border-radius: 999px; background: var(--gh-sand); font-size: 1rem;
}
.care-feed { margin-top: 14px; }
.care-feed > li { position: relative; padding: 4px 0 18px 30px; border-top: 0; }
.care-feed > li::before {
  content: ''; position: absolute; left: 4px; top: 10px; width: 12px; height: 12px; border-radius: 50%;
  background: var(--gh-rose); box-shadow: 0 0 0 4px #fff, 0 0 0 5px rgba(168, 67, 90, .25);
}
.care-feed > li[data-feed-kind="checkin"]::before { background: var(--gh-marigold); box-shadow: 0 0 0 4px #fff, 0 0 0 5px rgba(240, 176, 79, .4); }
.care-feed > li[data-feed-kind="answered"]::before { background: var(--gh-sage); box-shadow: 0 0 0 4px #fff, 0 0 0 5px rgba(107, 127, 106, .3); }
.care-feed > li:not(:last-child)::after { content: ''; position: absolute; left: 9px; top: 26px; bottom: 0; border-left: 2px solid var(--gh-line); }
.care-feed .feed-text { font-weight: 700; }
.care-feed .feed-meta { color: var(--gh-dusk); font-size: 1rem; font-variant-numeric: tabular-nums; }

/* Settings-style list rows */
.saved-places { gap: 0; margin-top: 14px; border: 1px solid rgba(237, 211, 170, .9); border-radius: var(--ui-radius-sm); overflow: hidden; }
.saved-places li { min-height: 60px; padding: 10px 16px; gap: 14px; background: #fff; }
.saved-places li + li { border-top: 1px solid rgba(237, 211, 170, .9); }
.saved-places svg { width: 36px; height: 36px; padding: 7px; border-radius: 10px; background: var(--gh-sand); }
.saved-places span { margin-left: auto; padding: 4px 12px; border-radius: 999px; background: var(--gh-marigold); color: var(--gh-ink); font-size: .9375rem; font-weight: 700; }

.message-list li { border-radius: 4px var(--ui-radius-sm) var(--ui-radius-sm) var(--ui-radius-sm); background: var(--gh-cream); border-color: rgba(237, 211, 170, .9); }
.message-meta { font-variant-numeric: tabular-nums; }

.email-settings { display: grid; gap: 0; margin: 12px 0 0; border: 1px solid rgba(237, 211, 170, .9); border-radius: var(--ui-radius-sm); overflow: hidden; }
.email-settings > div { display: grid; gap: 2px; padding: 12px 16px; background: #fff; }
.email-settings > div + div { border-top: 1px solid rgba(237, 211, 170, .9); }
.email-settings dt { color: var(--gh-dusk); font-size: .9375rem; }
.email-settings dd { margin: 0; font-weight: 700; overflow-wrap: anywhere; }
.account-panel h3 { margin-top: 12px; font-size: 1.0625rem; }
.settings-note { margin-top: 10px; color: var(--gh-dusk); font-size: .9375rem; }

/* Empty states */
.journey-empty, .care-feed-empty, .family-view .help-panel:not(.has-request) > p:not(.email-status) {
  margin-top: 12px; padding: 14px 16px; border: 1.5px dashed var(--gh-line); border-radius: var(--ui-radius-sm); background: var(--gh-cream);
  color: var(--gh-dusk);
}
.family-view .help-panel:not(.has-request) > .email-status:empty { display: none; }

/* ---------- Forms ---------- */
.reminder-form textarea, .onboarding-field input, .onboarding-field select {
  border: 2px solid var(--gh-line); border-radius: var(--ui-radius-sm); background: var(--gh-cream);
  transition: border-color .2s ease, box-shadow .2s ease, background-color .2s ease;
}
.reminder-form textarea:hover { border-color: var(--gh-violet); }
.reminder-form textarea:focus { border-color: var(--gh-rose); background: #fff; box-shadow: 0 0 0 4px rgba(168, 67, 90, .15); }
.reminder-form label { font-weight: 700; }

/* ---------- Footer ---------- */
footer { max-width: 76rem; padding: 20px 24px 32px; border-top: 0; }

@media (max-width: 700px) {
  .page { padding: 18px 16px 48px; }
  .site-header.app-bar { min-height: 68px; padding: 10px 16px; gap: 12px; }
  .app-mark { width: 40px; height: 40px; border-radius: 12px; }
  .app-subtitle { font-size: .9375rem; }
  .today-view .today-section, .family-view .panel, .family-view .panel:not(.has-request, .demo-controls), .patient-actions { padding: 18px; }
  .family-view .caring-card { padding: 20px; }
}
@media (prefers-reduced-motion: reduce) {
  .reminder-form textarea, .onboarding-field input, .onboarding-field select { transition: none; }
}
@media (forced-colors: active) {
  .icon-heading svg, .app-mark { border: 1px solid CanvasText; }
}

/* Demo hint under a movable map. */
.map-hint { display: flex; align-items: center; gap: 8px; padding: 10px 20px 0; color: var(--gh-dusk); font-size: 1rem; }
.map-hint svg { flex: none; width: 20px; height: 20px; color: var(--gh-rose); }
.journey-panel .map-hint { padding: 12px 20px 0; }
```

### 3a. `client/src/Shell.jsx`: the app bar

Add the sun app icon and a subtitle that reads "What's Next? · <today's date>". Format the date with the page language, so it doesn't show in the browser's language (Russian, for example) inside an English page.

```diff
diff --git a/client/src/Shell.jsx b/client/src/Shell.jsx
index c855153..e6f2bfe 100644
--- a/client/src/Shell.jsx
+++ b/client/src/Shell.jsx
@@ -1,4 +1,9 @@
 import { useEffect } from 'react'
+import Icon from './Icon.jsx'
+
+// Match the page language so the date doesn't switch languages mid-header.
+const today = () =>
+  new Date().toLocaleDateString(document.documentElement.lang || 'en', { weekday: 'long', month: 'long', day: 'numeric' })
 
 // Each dashboard is its own screen. The role comes only from the URL it was opened at.
 export default function Shell({ family, heading, plainBrand = false, action, footer, children }) {
@@ -11,10 +16,14 @@ export default function Shell({ family, heading, plainBrand = false, action, foo
   return (
     <>
       <a className="skip-link" href="#main">Skip to content</a>
-      <header className="site-header">
-        {plainBrand
-          ? <p className="brand person-name">What’s Next?</p>
-          : <h1 className="brand person-name">{title}</h1>}
+      <header className="site-header app-bar">
+        <span className="app-mark" aria-hidden="true"><Icon name="sun" /></span>
+        <div className="app-title">
+          {plainBrand
+            ? <p className="brand person-name">What’s Next?</p>
+            : <h1 className="brand person-name">{title}</h1>}
+          <p className="app-subtitle">{plainBrand ? title : `What’s Next? · ${today()}`}</p>
+        </div>
         {action && <div className="header-action">{action}</div>}
       </header>
       <main id="main" className={family ? 'page family-page' : 'page today-page'}>{children}</main>
```

### 3b. `client/src/CareScreens.jsx`: layout only, no logic changes

- **Patient screen (`TodayScreen`):** render the check-in section first. Then wrap the Reminders section, `PatientActions` and the confirmation block in `<div className="today-side">`. Then the journey (`TodayJourney`). On desktop, `app-ui.css` puts the journey on the left and pins `.today-side` on the right.
- **Care screen (`CaregiverDashboard`):** keep the "caring" hero card on top, then split the rest into two columns:
  - `<div className="care-main">`: help panel, journey panel (add class `journey-card`), caregiver feed;
  - `<div className="care-side">`: the reminder and calendar row, messages, saved places (add class `saved-card`), account.

  Keep every `can(...)` check exactly as it is.

## 4. Warmer, smoother map card (dashboards)

In `client/src/App.css` (already included in the `ui` commits):

- **`.journey-panel`:** `border: 1px solid var(--gh-line); border-radius: 24px; box-shadow: 0 2px 4px rgba(110,86,131,.06), 0 14px 34px rgba(110,86,131,.14);`
- **`.journey-map`:** a sand-to-cream shimmer background while the map loads, animated 2.8s only when motion is allowed. Add a `::after` with an inset soft edge (`pointer-events: none`).
- **Fade-in:** `.journey-map iframe` gets `transition: opacity .7s ease, visibility 0s`, and `.map-pending` gets `opacity: 0`, so the map fades in instead of popping in.
- **`.journey-strip`:** cream-to-white gradient background, `var(--gh-line)` top border, and a small rose dot before "Last known location".
- **`.map-note`:** a pill shape with a soft shadow.

In `client/src/JourneyMap.jsx` (the backup Leaflet drawing):
- the route is a plum line (`#6E5683`, weight 5) over a cream edge line (`#FFF6E8`, weight 11);
- safe zones are sage `#6B7F6A` dashes;
- the start is a plum dot and the destination a rose dot (`#A8435A`) with its name;
- the last known location is an ink dot with a cream border and a marigold halo.

In `backend/viewer/index.html` (the Leaflet viewer):
- warm tiles via `.leaflet-tile-pane { filter: sepia(.22) saturate(.9) brightness(1.03) hue-rotate(-8deg); }`;
- cream pill tooltips;
- rounded cream zoom buttons;
- smoother zoom via `L.map("map", { zoomSnap: 0.25, zoomDelta: 0.5, wheelPxPerZoomLevel: 120 })`.

In `backend/viewer/live-map.html` (the Google map), when it's embedded in a dashboard:
- force a light map (`colorScheme: EMBED ? "LIGHT" : "FOLLOW_SYSTEM"`);
- add a light apricot wash over the map (`.embed .mapcard::after`, `mix-blend-mode: multiply`, opacity .16);
- color the route and distance bands plum, the safe zones sage, and the markers as pill labels (`.mk.a` plum, `.mk.b` rose);
- give the current-position dot a marigold halo.

## 5. Behavior changes (small, optional but recommended)

1. **Move the walker on the demo map** (commit `bcd66fb`). Applies only in the open demo, when no care circle is used.
   - **API:** add `moveLocation(journeyId, lat, lng, timestamp)` to `client/src/data/journeyApi.js`. It posts to `/journeys/{id}/location`, and is `null` when a circle is used.
   - **Timestamps:** in `client/src/BackendDemo.jsx`, `moveLocation` sends each point one minute after the previous one. A replayed walk stays on its own simulated clock, and a live walk keeps up with the real clock.
   - **Wiring:** pass it through `CareScreens.jsx` to `JourneyMap` as `onMove`.
   - **Backup map:** click anywhere to move, or drag the dark dot.
   - **Google map:** the embed posts `{ type: "whats-next-map", status: "move", latitude, longitude }` to the dashboard on a click or a dot drag. The dashboard sends `movable` together with the journey message.
   - **Hint:** under the map, show "Tap the map, or drag the dark dot, to move the location."
2. **Live map: typing places works again** (commit `b22b830`). Google retired `google.maps.places.Autocomplete` for new projects in March 2025, so the From/To boxes showed no suggestions.
   - **Search endpoint:** add `backend/app/place_search.py` and `GET /api/places/search?q=&lat=&lng=`.
     - It tries Google Places API (New) Text Search with the server key first, then falls back to OpenStreetMap (Photon).
     - Results are limited to Montreal and cached.
     - A refused Google call is skipped for 10 minutes.
     - `PLACE_SEARCH_FALLBACK=off` turns the fallback off.
   - **Reverse lookup:** add `GET /api/places/reverse?lat=&lng=` so a spot picked on the map is named after its address.
   - **Tests:** add `backend/tests/test_place_search.py`.
   - **Map loader:** in `live-map.html`, drop the `places` library from the Google Maps loader.
   - **Suggestion list:** build an accessible combobox with `role="combobox"`, a `role="listbox"` suggestion list, arrow keys, Enter and Escape.
   - **Also add:** a ⇅ swap button and FROM/TO labels. Typing places and routing must work even when the Google map can't load.

## 6. Live map page restyle (`backend/viewer/live-map.html`, commit `b22b830`)

- **Color tokens:**
  - base: `--bg #FFF6E8`, `--surface #fff`, `--ink #3B2B45`, `--muted #5B4A6E`, `--line #EDD3AA`, `--grid #FDE9C4`;
  - purple accent: `--accent #6E5683`, `--accent-soft #EFE6F3`;
  - rose: `--rose #A8435A`, `--rose-deep #8E3549`;
  - risk: `--low #3D6B47 / #E5F0E1`, `--med #8A5410 / #FDECC8`, `--high #A8352A / #FBE2DA`.
- **Dark mode:** a deep plum version (`--bg #1F1726`, `--surface #2A2033`, `--accent #C9A7E2`, and so on).
- **Font:** Atkinson Hyperlegible Next for everything, with JetBrains Mono kept for numbers.
- **Header:** a hero band with `linear-gradient(135deg, #6E5683, #8C4A6C 60%, #A8435A)`, white text, a sun icon in a frosted tile, and a soft sun glow in the corner.
- **Cards:** 20px radius with a soft shadow.
- **Buttons:**
  - pills at least 40px tall with a 2px border;
  - hover: plum border with `--accent-soft` background;
  - pressed or active state: plum fill;
  - main button: rose fill with a `0 3px 0` deep-rose shadow.
- **Inputs:** 46px tall, 14px radius, cream fill, and a plum border plus a soft ring on focus.
- **Planner:** FROM (plum dot) and TO (rose pin) joined by a dotted plum line, like a maps app, with the swap button on the right.
- **Scenario cards and chips:**
  - scenario cards get a 16px radius and a plum `--accent-soft` background when hovered or selected;
  - tags become sand pills;
  - risk level chips become rounded pills.

## Check when done

- [ ] `npm run lint`, `npm test` and `npm run build` pass in `client/`; `pytest` passes in `backend/`.
- [ ] The role picker, Patient dashboard and Care dashboard look right at phone width (375px) and desktop width (1280px), with no sideways scrolling.
- [ ] Keyboard Tab shows a visible ink focus ring everywhere. With "reduce motion" on, nothing animates.
- [ ] On the live map, typing "Jean-Talon Market" shows suggestions, choosing one redraws the walking route, "Pick on map" names the spot by its address, and ⇅ swaps From and To.
- [ ] On the dashboard map (demo), clicking or dragging the dot moves the location and updates "Last known location".
