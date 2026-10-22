# RoomSync

A web dashboard for booking classrooms, labs and meeting rooms, with live
"are people in this room?" detection from a camera.

College IoT mini project, CSE department, JSS Academy of Technical Education,
Bengaluru. Team: Deeptanshu Pandey (backend, frontend), Dhanvanth (camera
module), Chirag S, Gagan SS.

## What it does

Every room shows two separate things side by side, for example
"Reserved · People detected":

- **Booking status**: `not_booked`, `scheduled` (regular timetable class),
  `reserved` (one-time booking such as an extra class or meeting),
  `overridden`, `released` (freed by the no-show check), `cancelled`.
- **Occupancy**: `people_detected`, `not_detected`, `no_data`.

The camera only detects whether people are present and counts them. It never
identifies anyone and never confirms that a class is happening. No camera
image is ever stored.

Roles:

- **Student**: views rooms, the timetable, bookings and occupancy.
- **CR**: a student chosen by their class teacher; gets notifications about
  their class's bookings.
- **Teacher**: reserves free rooms, schedules extra classes, cancels their own
  reservations.
- **Admin**: a teacher with admin rights; can override, reschedule or remove a
  booking, always with a reason. The teacher and the class CR are notified.
- **Super admin**: one account that grants and removes admin rights.

## Parts of the project

| Folder | What it is | Details |
| --- | --- | --- |
| [`backend/`](backend/) | FastAPI + PostgreSQL server: logins, rooms, bookings, occupancy, notifications | [backend/README.md](backend/README.md) |
| [`docs/`](docs/) | The agreed request and reply formats for every endpoint | [docs/API_CONTRACT.md](docs/API_CONTRACT.md) |
| [`camera-model-test/`](camera-model-test/) | Python server that runs YOLOv8 on camera frames and counts people | [camera-model-test/README.md](camera-model-test/README.md) |
| [`RoomSyncMobile/`](RoomSyncMobile/) | Expo (React Native) phone app that acts as the camera | [RoomSyncMobile/README.md](RoomSyncMobile/README.md) |

How the pieces connect:

```text
Phone app ──frames──> camera-model-test ──people count──> backend ──> dashboard
(RoomSyncMobile)      (YOLOv8, laptop)                    (FastAPI + PostgreSQL)
```

## Quick start

All commands are for Windows PowerShell.

- **Backend**: follow "First-time setup" in [backend/README.md](backend/README.md),
  then run `uvicorn app.main:app --reload` inside `backend/` and open
  http://127.0.0.1:8000/docs.
- **Camera module**: follow [camera-model-test/README.md](camera-model-test/README.md)
  to start the inference server and the phone app.

## Status

- Backend: login, rooms, room status grid, bookings, admin changes with
  reasons, camera readings and notifications are done and tested.
- Camera module: works on its own; not yet sending readings to the backend.
- Still to do: timetable upload, no-show check, admin rights, choosing the CR,
  first-login setup codes, and the web frontend.
