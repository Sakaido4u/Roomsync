"""Timed background jobs, started and stopped with the server (see main.py).

Right now there is one job: the no-show check, every minute.
"""

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import IST, settings
from app.no_show import run_no_show_check


def start_scheduler() -> BackgroundScheduler | None:
    if not settings.background_jobs:
        return None
    scheduler = BackgroundScheduler(timezone=IST)
    scheduler.add_job(
        run_no_show_check,
        "interval",
        minutes=1,
        id="no_show_check",
        # If one run is slow, skip overlapping runs instead of piling them up.
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler
