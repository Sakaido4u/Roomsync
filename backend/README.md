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
│   ├── errors.py     Error replies in the contract's format
│   ├── security.py   Password hashing
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

After changing `models.py`, run `python -m app.init_db --reset` and then
`python -m app.seed`, because existing tables are not updated automatically.
