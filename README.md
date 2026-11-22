# Lark

**A walking app for people living with dementia, such as Alzheimer's: more independence for them, less worry for their family.**

Most safety apps answer *"Where is she?"*. Lark answers *"Is she getting lost?"*.
She walks on her own, and her family is only contacted when something looks wrong.

## How it works

1. She picks where she is going. Lark gets the real walking route from Google.
2. Every GPS point is compared with that route and turned into a **risk score from 0 to 100**.
3. **30+:** her phone asks *"Are you okay?"* **60+:** her family gets an alert that says why.
4. **Optional:** connect a Google account so alerts are also emailed to the family (Gmail) and upcoming visits come from Google Calendar.

| What Lark notices | Points |
|---|---|
| Off the route | 10 to 40, more the further and longer she is off |
| Standing still | 3 per minute, after 2 minutes |
| Walking in circles | 15 each time she comes back to the same spot |
| Left the destination after arriving | 15 |
| Taking much longer than expected | 2 per minute |
| Didn't answer "Are you okay?" | +15 |
| Answered "I'm okay" | −15 |

The full rules are in [backend/README.md](backend/README.md).

## Built with

Python + FastAPI (backend) · React (frontend) · Google Maps, Routes, Gmail and Calendar · Supabase

## Run it

**Backend**

```sh
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

**Frontend** (in a second terminal)

```sh
cd client
npm install
npm run dev
```

Open `http://localhost:5173/signup` in two windows: choose **I'm signing up for myself** in one and **I'm a caregiver** in the other. Start a walk, then tap the map away from the route to see the check-in and the alert.

No Google keys needed to try it.
