"""Forward people counts from the inference server to the RoomSync backend.

After YOLO counts the people in a frame, this module turns the count into a
reading for the backend's POST /api/occupancy (API contract endpoint 20).
The device key stays here on the laptop; the phone never sees it.

Two small ideas keep this simple and safe:

- Smoothing: a single bad frame should not make a room flicker between
  "people detected" and "not detected". For each room we remember the last
  3 counts and only change our answer when all 3 agree.
- Pausing: if the backend says no (wrong key, unknown room) or cannot be
  reached, we do not hammer it. That room waits PAUSE_AFTER_FAILURE_SECONDS
  before the next try. The phone still gets its people count every time.

This file only uses Python's standard library, so its tests run without the
camera, the YOLO model or a real backend.
"""

import datetime as dt
import json
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from threading import Lock
from typing import Callable

# India time, the same fixed +05:30 offset the backend uses.
IST = dt.timezone(dt.timedelta(hours=5, minutes=30), name="IST")

AGREE_FRAMES = 3
PAUSE_AFTER_FAILURE_SECONDS = 10
REQUEST_TIMEOUT_SECONDS = 3
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"

# post(url, headers, json_body, timeout) -> (status_code, reply_text).
# Raises OSError when the backend cannot be reached at all.
PostFunction = Callable[[str, dict, dict, float], tuple[int, str]]


def load_env(path: Path) -> dict[str, str]:
    """Read KEY=VALUE lines from a .env file. A missing file gives {}."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def http_post(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, str]:
    """Send a JSON POST and return (status code, reply text), even for 4xx/5xx."""
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.status, reply.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        # The backend answered, just not with success: that is a reply, not a crash.
        return error.code, error.read().decode("utf-8", "replace")


class Smoother:
    """Per room, only flip people_detected when the last AGREE_FRAMES counts agree."""

    def __init__(self, agree_frames: int = AGREE_FRAMES):
        self.agree_frames = agree_frames
        self._recent: dict[str, deque[bool]] = {}
        self._answer: dict[str, bool] = {}

    def update(self, room_id: str, count: int) -> bool:
        seen = count > 0
        recent = self._recent.setdefault(room_id, deque(maxlen=self.agree_frames))
        recent.append(seen)
        if room_id not in self._answer:
            # First frame for this room: nothing to compare with yet, so start from it.
            self._answer[room_id] = seen
        elif len(recent) == self.agree_frames and all(r == seen for r in recent):
            self._answer[room_id] = seen
        return self._answer[room_id]


def build_reading(room_id: str, count: int, people_detected: bool, now: dt.datetime) -> dict:
    """The JSON body for POST /api/occupancy.

    The backend insists that head_count matches people_detected, so when the
    smoothed answer and this frame's count disagree we adjust head_count:
    - smoothed "detected" but this frame saw 0 -> head_count null (unknown)
    - smoothed "not detected" but this frame saw some -> head_count 0
    """
    if people_detected:
        head_count = count if count > 0 else None
    else:
        head_count = 0
    return {
        "room_id": room_id,
        "people_detected": people_detected,
        "head_count": head_count,
        "camera_status": "online",
        "time": now.isoformat(),
    }


def _reason_from_reply(status: int, text: str, room_id: str) -> str:
    """A short, readable reason for a failed reply, shown on the phone."""
    if status == 401:
        return "backend refused the device key (check DEVICE_KEY in camera-model-test/.env)"
    if status == 404:
        return f"room {room_id} does not exist on the backend"
    try:
        message = json.loads(text).get("message")
    except (ValueError, AttributeError):
        message = None
    return f"backend replied {status}" + (f": {message}" if message else "")


class BackendSync:
    """Smooths counts and sends them to the backend, pausing a room after a failure."""

    def __init__(
        self,
        backend_url: str,
        device_key: str,
        post: PostFunction = http_post,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(IST),
    ):
        self.backend_url = backend_url.rstrip("/")
        self.device_key = device_key
        self._post = post
        self._clock = clock
        self._now = now
        self._smoother = Smoother()
        # room_id -> (clock time when sending may resume, reason it was paused)
        self._paused: dict[str, tuple[float, str]] = {}
        self._lock = Lock()

    @classmethod
    def from_env_file(cls, path: Path) -> "BackendSync":
        env = load_env(path)
        return cls(env.get("BACKEND_URL") or DEFAULT_BACKEND_URL, env.get("DEVICE_KEY", ""))

    def send(self, room_id: str, count: int) -> dict:
        """Record one frame's count and try to send it.

        Returns {"backend_status": "synced"} or
        {"backend_status": "not_synced", "backend_error": "<reason>"}.
        Never raises: the phone should always get its count back.
        """
        with self._lock:
            people_detected = self._smoother.update(room_id, count)
            paused = self._paused.get(room_id)
            if paused and self._clock() < paused[0]:
                wait = int(paused[0] - self._clock()) + 1
                return _not_synced(f"{paused[1]} (retrying in {wait} s)")

        if not self.device_key:
            return _not_synced("DEVICE_KEY is not set in camera-model-test/.env")

        reading = build_reading(room_id, count, people_detected, self._now())
        try:
            status, text = self._post(
                f"{self.backend_url}/api/occupancy",
                {"X-Device-Key": self.device_key},
                reading,
                REQUEST_TIMEOUT_SECONDS,
            )
        except OSError:
            # Covers "connection refused", timeouts and unknown host names.
            reason = f"backend unreachable at {self.backend_url}"
        else:
            if 200 <= status < 300:
                with self._lock:
                    self._paused.pop(room_id, None)
                return {"backend_status": "synced"}
            reason = _reason_from_reply(status, text, room_id)

        with self._lock:
            self._paused[room_id] = (self._clock() + PAUSE_AFTER_FAILURE_SECONDS, reason)
        return _not_synced(reason)


def _not_synced(reason: str) -> dict:
    return {"backend_status": "not_synced", "backend_error": reason}
