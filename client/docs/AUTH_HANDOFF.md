# Google sign-in and care circle handoff

This is the API the onboarding UI expects. It is a proposal for the teammate who owns Google sign-in and circle permissions, so names can change. `client/dev/fictionalAuth.js` implements it for local UI testing only and must not ship.

## What the backend must enforce

- Verify the Google identity on the server and keep the session in an `HttpOnly`, `Secure`, `SameSite` cookie.
- Check circle membership on **every** circle read and write.
- Never use the onboarding role to grant access. It is user input.
- Return the same `403` for an unknown circle and a circle the account can't access.
- **Close the current open routes.** `/api/journeys*`, `/api/alerts*`, `/api/events`, `/api/demo/*`, and the viewer's calls to them need no sign-in today. This also applies to `origin/artem_branch`. Until they are closed, the UI gate does not protect real data.
- `POST /api/demo/reset` clears every circle. Scope it to one circle or disable it outside demos.

## Endpoints

Errors use the existing shape: `{ "error": { "code", "message", "details": { "field" } } }`. `details.field` places the message beside the right input.

| Method and path | Purpose | Responses |
|---|---|---|
| `GET /api/auth/google/start` | Begin Google sign-in | Redirect |
| `GET /api/auth/session` | Current account | `200` session, `401` |
| `POST /api/auth/sign-out` | End session | `200` |
| `PUT /api/onboarding/role` | Save `{ "role": "self" \| "caregiver" \| "family" }` | `200` session, `422` field `role` |
| `POST /api/circles` | Create from `{ "name" }` | `201` circle, `422` field `name` |
| `POST /api/circles/join` | Join from `{ "code" }` | `200` circle, `404` or `422` field `code` |
| `GET /api/circles/{id}` | Authorize a dashboard | `200` circle, `401`, `403` |
| `GET`, `PUT /api/circles/{id}/reminder` | Read or send `{ "message" }` | `200`, `401`, `403`, `422` |
| `GET`, `POST /api/circles/{id}/journeys` | Read or start that circle's journeys | `200` or `201`, `401`, `403` |
| `GET /api/circles/{id}/journeys/{journey}/checkins` | Check-ins | `200`, `401`, `403` |
| `POST /api/circles/{id}/journeys/{journey}/checkin` | Answer or request help | `200`, `401`, `403` |
| `POST /api/circles/{id}/journeys/{journey}/complete` or `/cancel` | End a journey | `200`, `401`, `403` |
| `GET /api/circles/{id}/alerts?journey_id=&acknowledged=` | That circle's alerts | `200`, `401`, `403` |

After Google sign-in, redirect to `/onboarding`. On failure, redirect to `/onboarding?auth_error=1`.

Session shape. Each circle lists the permissions the **server** granted, usually from the invite:

```json
{
  "account": { "id": "acct_1", "name": "Fictional Person", "given_name": "Fictional" },
  "role": "family",
  "circles": [{
    "id": "circle_1",
    "name": "Fictional care circle",
    "permissions": ["view_today", "view_dashboard", "read_reminders", "send_reminders", "read_journey", "start_journey", "read_help", "request_help"],
    "care_recipient": { "id": "acct_2", "name": "Fictional Relative", "given_name": "Fictional" },
    "caregivers": [{ "id": "acct_1", "name": "Fictional Person", "given_name": "Fictional", "relationship": "friend", "photo_url": "/fictional.jpg", "phone": "configured-number" }]
  }]
}
```

`GET /api/circles/{id}`, `POST /api/circles`, and `POST /api/circles/join` return the same circle object. `view_today` and `view_dashboard` choose the layouts a person can open. Enforce every permission on its route. The onboarding role must never grant access.

`care_recipient` is `null` when nobody is linked. `relationship`, `photo_url`, and `phone` are optional. On a caregiver, `relationship` describes them relative to the care recipient. On `care_recipient`, it describes that person relative to the signed-in viewer.

`GET /api/circles/{id}/reminder` returns `{ "message": "...", "sender": { person } }`, or `null` for both. Set the sender from the session, never from the request body.

Help currently requires a journey, so the client creates and closes a placeholder journey when someone asks for help before a walk. A `POST /api/circles/{id}/help` endpoint would remove that workaround. The open demo similarly stores reminders as closed `Demo reminder` journeys until the reminder routes exist.

## Turning it on

Build the client with `VITE_AUTH_REQUIRED=true` once these routes exist. The default build stays in open demo mode. Run the fictional version with `npm run dev:onboarding`. Its **Continue with Google** button reports that sign-in is pending. Post-sign-in screens are tested separately from `/test-session`.
