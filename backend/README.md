# RoomSync backend

FastAPI + PostgreSQL server for RoomSync. The request and reply formats
are fixed in [`docs/API_CONTRACT.md`](../docs/API_CONTRACT.md).

## Folder layout

```
backend/
├── app/
│   ├── main.py       Starts the app; endpoints get plugged in here
│   ├── config.py     Reads settings from .env
│   ├── database.py   Connection to PostgreSQL
│   ├── models.py     The database tables and the no-overlap rule
│   ├── schemas.py    Request/reply shapes from the API contract
│   ├── errors.py     Error replies in the contract's format
│   ├── security.py   Passwords, login tokens, role checks
│   ├── timeutil.py   Date + "HH:MM" <-> India-time date-times
│   ├── occupancy.py  Latest camera reading -> people_detected / not_detected / no_data
│   ├── notify.py     Creates notifications and sends their email copies
│   ├── routers/
│   │   ├── auth.py      Login, current user (endpoints 3, 4)
│   │   ├── bookings.py  Reserve, my bookings, cancel (endpoints 12-14)
│   │   ├── rooms.py     Room list, status grid, schedule, add room (endpoints 8-11)
│   │   ├── occupancy.py Camera readings in, latest reading out (endpoints 20, 21)
│   │   ├── booking_changes.py  Admin override, reschedule, remove (endpoints 15-17)
│   │   └── notifications.py    My notifications, mark as read (endpoints 22, 23)
│   ├── init_db.py    Creates (or resets) the tables
│   └── seed.py       Adds demo users, rooms and bookings
├── tests/            Automated tests (pytest)
├── requirements.txt
└── .env.example      Copy to .env and fill in
```

## First-time setup (Windows PowerShell)

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # then edit .env with your postgres password
```

In SQL Shell (psql), create the test database once:

```sql
CREATE DATABASE roomsync_test;
\c roomsync_test
CREATE EXTENSION btree_gist;
```

## Everyday commands (venv active, inside backend/)

| What | Command |
| --- | --- |
| Start the server | `uvicorn app.main:app --reload` |
| Try the API in the browser | open http://127.0.0.1:8000/docs |
| Add demo data | `python -m app.seed` |
| Wipe and recreate all tables | `python -m app.init_db --reset` |
| Run the tests | `pytest -v` |

Demo accounts all use the password `roomsync123`: `SA001` (super admin),
`T001` (admin/HOD), `T002` and `T003` (teachers), `1JS23CS044` (student, CR),
`1JS23CS039` (student).

## Trying logged-in endpoints on /docs

1. Open `POST /api/auth/login` → **Try it out**, enter
   `{"college_id": "T002", "password": "roomsync123"}` → **Execute**.
2. Copy the `token` value from the reply (without the quotes).
3. Click the **Authorize** button at the top of the page, paste the token, **Authorize**.
4. Every request from the page now includes your login, e.g. `POST /api/bookings`.

## Done so far (API contract)

| # | Endpoint | Status |
| --- | --- | --- |
| 3, 4 | Login, current user | Done |
| 8, 9, 10, 11 | Room list, room status grid, room schedule, add room | Done |
| 12, 13, 14 | Reserve, my bookings, cancel | Done |
| 15, 16, 17 | Admin override, reschedule, remove (with reason) | Done |
| 20, 21 | Camera readings in, latest reading out | Done |
| 22, 23 | My notifications, mark as read | Done |
| others | Setup codes, admin rights, CR, timetable, no-show | To do |

## For the camera program

The camera program sends one reading per room every few seconds to
`POST /api/occupancy`, with the header `X-Device-Key` set to the same value
as `DEVICE_KEY` in the backend's `.env`. Example in Python:

```python
import datetime as dt
import requests

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

requests.post(
    "http://127.0.0.1:8000/api/occupancy",
    headers={"X-Device-Key": "PASTE-THE-DEVICE-KEY-HERE"},
    json={
        "room_id": "CSE-101",
        "people_detected": True,        # False if nobody is seen
        "head_count": 23,               # 0 when people_detected is False
        "camera_status": "online",      # "offline" if the camera can't be read
        "time": dt.datetime.now(IST).isoformat(),
    },
    timeout=3,
)
```

Rules the backend checks (each breaks with `400 invalid_input`):
- `online` readings must say `people_detected` true or false, not null.
- `people_detected: false` needs `head_count` 0; `true` needs 1 or more (or null).
- `time` cannot be more than 2 minutes in the future (check the PC's clock).

For an `offline` camera, send `people_detected: null` and `head_count: null`.
Wrong key: `401`. Unknown `room_id`: `404` (rooms come from `python -m app.seed`
or `POST /api/rooms`). A room shows `no_data` on the dashboard if its last
reading is over 60 seconds old, so keep sending even when nothing changes.

After changing `models.py`, run `python -m app.init_db --reset` and then
`python -m app.seed`, because existing tables are not updated automatically.
