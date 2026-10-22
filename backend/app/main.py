"""RoomSync backend entry point.

Start the server from the backend folder, with the venv active:

    uvicorn app.main:app --reload

Then open http://127.0.0.1:8000/docs to see and try every endpoint.
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR
from app.database import get_db
from app.errors import ApiError, register_error_handlers
from app.init_db import create_tables
from app.scheduler import start_scheduler
from app.routers import (
    admin,
    auth,
    booking_changes,
    bookings,
    classes,
    no_show_response,
    notifications,
    occupancy,
    rooms,
    timetable,
)


FRONTEND_DIR = BACKEND_DIR.parent / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Make sure all tables exist before the first request.
    create_tables()
    # Start the every-minute no-show check; stop it when the server stops.
    scheduler = start_scheduler()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


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
app.include_router(timetable.router)
app.include_router(no_show_response.router)
app.include_router(admin.router)
app.include_router(classes.router)

# The web dashboard (plain HTML, CSS and JavaScript in ../frontend) is served
# from the same server at http://127.0.0.1:8000/, so it can call /api/...
# directly. Mounted last, so every /api and /docs address above wins.
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
