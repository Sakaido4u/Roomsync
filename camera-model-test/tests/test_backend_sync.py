"""Tests for forwarding people counts to the backend.

No camera, YOLO model or real backend is needed: a fake post() function
records what would have been sent and returns whatever reply we choose,
and a fake clock lets us skip over the pause without waiting.
"""

import datetime as dt

import pytest

from backend_sync import (
    IST,
    PAUSE_AFTER_FAILURE_SECONDS,
    BackendSync,
    Smoother,
    build_reading,
    load_env,
)

NOW = dt.datetime(2026, 11, 3, 15, 4, 10, tzinfo=IST)


class FakeBackend:
    """Stands in for http_post: records each call and replies as told."""

    def __init__(self, status=201, text='{"received": true}', error=None):
        self.status, self.text, self.error = status, text, error
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": body})
        if self.error:
            raise self.error
        return self.status, self.text


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_sync(backend, clock=None, key="test-device-key-123"):
    return BackendSync("http://backend:8000/", key, post=backend,
                       clock=clock or FakeClock(), now=lambda: NOW)


# --- What gets sent -------------------------------------------------------

def test_sends_reading_in_contract_format():
    backend = FakeBackend()
    result = make_sync(backend).send("CSE-101", 4)

    assert result == {"backend_status": "synced"}
    call = backend.calls[0]
    assert call["url"] == "http://backend:8000/api/occupancy"
    assert call["headers"] == {"X-Device-Key": "test-device-key-123"}
    assert call["body"] == {
        "room_id": "CSE-101",
        "people_detected": True,
        "head_count": 4,
        "camera_status": "online",
        "time": "2026-11-03T15:04:10+05:30",
    }


def test_zero_people_is_not_detected_with_head_count_zero():
    backend = FakeBackend()
    make_sync(backend).send("CSE-101", 0)
    body = backend.calls[0]["body"]
    assert body["people_detected"] is False
    assert body["head_count"] == 0


@pytest.mark.parametrize("detected, count, expected_head_count", [
    (True, 5, 5),
    (True, 0, None),    # smoothed "yes" but this frame saw nobody: count unknown
    (False, 0, 0),
    (False, 2, 0),      # smoothed "no" but this frame saw some: backend needs 0
])
def test_head_count_always_matches_people_detected(detected, count, expected_head_count):
    reading = build_reading("CSE-101", count, detected, NOW)
    assert reading["people_detected"] is detected
    assert reading["head_count"] == expected_head_count


# --- Smoothing ------------------------------------------------------------

def test_first_frame_sets_the_answer():
    assert Smoother().update("CSE-101", 3) is True
    assert Smoother().update("CSE-101", 0) is False


def test_one_odd_frame_does_not_flip():
    s = Smoother()
    s.update("R", 2)
    assert s.update("R", 0) is True
    assert s.update("R", 3) is True


def test_flips_only_after_three_agreeing_frames():
    s = Smoother()
    s.update("R", 2)                 # starts "detected"
    assert s.update("R", 0) is True
    assert s.update("R", 0) is True  # only 2 zeros in the last 3
    assert s.update("R", 0) is False # 3 zeros in a row: flip


def test_rooms_are_smoothed_separately():
    s = Smoother()
    s.update("A", 5)
    assert s.update("B", 0) is False
    assert s.update("A", 0) is True


def test_smoothed_answer_is_what_gets_sent():
    backend = FakeBackend()
    sync = make_sync(backend)
    for count in [3, 0, 0]:
        sync.send("CSE-101", count)
    last = backend.calls[-1]["body"]
    assert last["people_detected"] is True
    assert last["head_count"] is None


# --- Failures: report a reason, never crash, never hammer ----------------

@pytest.mark.parametrize("status, text, expected", [
    (401, '{"error": "not_logged_in", "message": "Missing or wrong device key."}',
     "backend refused the device key"),
    (404, '{"error": "not_found", "message": "Room X does not exist."}',
     "room CSE-101 does not exist on the backend"),
    (400, '{"error": "invalid_input", "message": "time is in the future."}',
     "backend replied 400: time is in the future."),
    (500, "Internal Server Error", "backend replied 500"),
])
def test_error_replies_give_a_reason(status, text, expected):
    result = make_sync(FakeBackend(status=status, text=text)).send("CSE-101", 1)
    assert result["backend_status"] == "not_synced"
    assert expected in result["backend_error"]


@pytest.mark.parametrize("error", [ConnectionRefusedError(), TimeoutError()])
def test_backend_down_gives_a_reason(error):
    result = make_sync(FakeBackend(error=error)).send("CSE-101", 1)
    assert result == {"backend_status": "not_synced",
                      "backend_error": "backend unreachable at http://backend:8000"}


def test_pauses_after_failure_then_tries_again():
    backend = FakeBackend(error=ConnectionRefusedError())
    clock = FakeClock()
    sync = make_sync(backend, clock)

    sync.send("CSE-101", 1)
    assert len(backend.calls) == 1

    clock.t += 3
    result = sync.send("CSE-101", 1)
    assert len(backend.calls) == 1, "should not call the backend while paused"
    assert "retrying in" in result["backend_error"]

    backend.error = None
    clock.t += PAUSE_AFTER_FAILURE_SECONDS
    assert sync.send("CSE-101", 1) == {"backend_status": "synced"}
    assert len(backend.calls) == 2


def test_pause_is_per_room():
    backend = FakeBackend(status=404, text="{}")
    sync = make_sync(backend)
    sync.send("NOPE-1", 1)
    backend.status, backend.text = 201, "{}"
    assert sync.send("CSE-101", 1) == {"backend_status": "synced"}


def test_smoothing_keeps_counting_while_paused():
    backend = FakeBackend(error=ConnectionRefusedError())
    clock = FakeClock()
    sync = make_sync(backend, clock)
    for count in [2, 0, 0, 0]:   # 3 zeros arrive during the pause
        sync.send("CSE-101", count)
    backend.error = None
    clock.t += PAUSE_AFTER_FAILURE_SECONDS
    sync.send("CSE-101", 0)
    assert backend.calls[-1]["body"]["people_detected"] is False


def test_missing_device_key_is_reported_without_calling_backend():
    backend = FakeBackend()
    result = make_sync(backend, key="").send("CSE-101", 1)
    assert backend.calls == []
    assert "DEVICE_KEY is not set" in result["backend_error"]


# --- Reading .env ---------------------------------------------------------

def test_load_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\n\nBACKEND_URL=http://10.0.0.5:8000\nDEVICE_KEY="abc=123"\n',
                   encoding="utf-8")
    assert load_env(env) == {"BACKEND_URL": "http://10.0.0.5:8000", "DEVICE_KEY": "abc=123"}


def test_missing_env_file_uses_defaults(tmp_path):
    sync = BackendSync.from_env_file(tmp_path / "missing.env")
    assert sync.backend_url == "http://127.0.0.1:8000"
    assert sync.send("CSE-101", 1)["backend_status"] == "not_synced"
