"""Create (or reset) the database tables.

Run from the backend folder, with the venv active:

    python -m app.init_db            # create any tables that don't exist yet
    python -m app.init_db --reset    # DELETE all tables and data, then recreate

Use --reset whenever models.py changes (a new column, a renamed field):
create_all only adds missing tables, it never changes existing ones.
"""

import sys

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app import models  # noqa: F401  (importing registers every table with Base)
from app.database import Base, engine


# Columns added to existing tables after they were first created. create_all
# never changes an existing table, so these are added here instead, keeping
# all data. "IF NOT EXISTS" makes them safe to run on every start.
UPGRADES = [
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS no_show_kept_at TIMESTAMPTZ",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_one_cr_per_class ON users (class_id) "
    "WHERE is_cr",
    "ALTER TABLE setup_codes ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0",
    # Timetable grid (handoff 2). The subjects table itself is new, so
    # create_all makes it before these run.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS initials VARCHAR(10)",
    "ALTER TABLE classes ADD COLUMN IF NOT EXISTS semester_label VARCHAR(20)",
    "ALTER TABLE classes ADD COLUMN IF NOT EXISTS home_room_id VARCHAR(20) "
    "REFERENCES rooms (room_id)",
    "ALTER TABLE classes ADD COLUMN IF NOT EXISTS strength INTEGER",
    "ALTER TABLE classes ADD COLUMN IF NOT EXISTS wef_date DATE",
    "ALTER TABLE timetable_entries ALTER COLUMN room_id DROP NOT NULL",
    "ALTER TABLE timetable_entries ADD COLUMN IF NOT EXISTS subject_code VARCHAR(20) "
    "REFERENCES subjects (code)",
    "ALTER TABLE timetable_entries ADD COLUMN IF NOT EXISTS batch VARCHAR(10)",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS subject_code VARCHAR(20) "
    "REFERENCES subjects (code)",
]


def create_tables(target: Engine = engine) -> None:
    with target.begin() as conn:
        # btree_gist lets the overlap rule compare room_id (a normal value)
        # and a time range in the same constraint.
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
    Base.metadata.create_all(target)
    with target.begin() as conn:
        for statement in UPGRADES:
            conn.execute(text(statement))


def drop_tables(target: Engine = engine) -> None:
    Base.metadata.drop_all(target)


def main() -> None:
    if "--reset" in sys.argv:
        answer = input("This deletes ALL RoomSync data. Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            print("Cancelled.")
            return
        drop_tables()
        print("All tables dropped.")
    create_tables()
    print("Tables ready:", ", ".join(sorted(Base.metadata.tables)))


if __name__ == "__main__":
    main()
