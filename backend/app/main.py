"""RoomSync backend entry point.

Start the server from the backend folder, with the venv active:

    uvicorn app.main:app --reload

Then open http://127.0.0.1:8000/docs to see and try every endpoint.
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ApiError, register_error_handlers
from app.init_db import create_tables
from app.routers import auth, booking_changes, bookings, notifications, occupancy, rooms


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Make sure all tables exist before the first request.
    create_tables()
    yield


app = FastAPI(
    title="RoomSync API",
    description="Room and lab booking with camera-based people detection. "
    "See docs/API_CONTRACT.md for the agreed request and reply formats.",
    version="0.1.0",
    lifespan=lifespan,
)

# Lets the dashboard call the API while it is opened from a different
# address during development (e.g. VS Code Live Server on port 5500).
# Tighten this list before a real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)


@app.get("/api/health", tags=["system"])
def health(db: Session = Depends(get_db)) -> dict:
    """Quick check that the server is up and can reach the database."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # database down, wrong password, etc.
        raise ApiError(503, "database_unavailable", f"Cannot reach the database: {exc}")
    return {"status": "ok", "database": "connected"}


# Endpoints from the API contract, one router per area. New areas
# (rooms, admin, occupancy, ...) get added to this list as they are built.
app.include_router(auth.router)
app.include_router(bookings.router)
app.include_router(rooms.router)
app.include_router(occupancy.router)
app.include_router(booking_changes.router)
app.include_router(notifications.router)
