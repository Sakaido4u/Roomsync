# RoomSync

A web dashboard for booking classrooms, labs and meeting rooms, with live
"are people in this room?" detection from a camera.

College IoT mini project, CSE department, JSS Academy of Technical Education,
Bengaluru. Team: Deeptanshu Pandey (backend, frontend), Dhanvanth (camera
module), Chirag S, Gagan SS.

## What it does

Every room shows two separate things side by side, for example
"Reserved · People detected":

- **Booking status**: Not booked, Scheduled (regular timetable class),
  Reserved (one-time booking such as an extra class or meeting), Overridden,
  Released (freed by the no-show check), Cancelled.
- **Occupancy**: People detected, Not detected, No camera data.

The camera only detects whether people are present and counts them. It never
identifies anyone and never confirms that a class is happening. No camera
image is ever stored.

Roles:

- **Student**: views rooms, bookings and occupancy.
- **CR**: a student chosen by their class teacher; gets notifications about
  their class's bookings and can answer no-show reminders.
- **Teacher**: reserves free rooms, schedules extra classes, cancels their own
  reservations.
- **Admin**: a teacher with admin rights; can override, reschedule or remove a
  booking, always with a reason (the teacher and the class CR are told),
  upload the timetable and add rooms.
- **Super admin**: one account that grants and removes admin rights.

If a teacher tries to book a taken slot, a pop-up shows who booked it, when,
why, and free rooms to book instead. If a booked room stays empty, the
no-show check reminds the teacher and CR after 15 minutes and frees the room
10 minutes later if nobody answers.

## Parts of the project

| Folder | What it is | Details |
| --- | --- | --- |
| [`backend/`](backend/) | FastAPI + PostgreSQL server: logins, rooms, bookings, timetable, no-show check, notifications. Also serves the dashboard. | [backend/README.md](backend/README.md) |
| [`frontend/`](frontend/) | The web dashboard: plain HTML, CSS and JavaScript, no build step | (served by the backend at `/`) |
| [`docs/`](docs/) | The agreed request and reply formats for every endpoint | [docs/API_CONTRACT.md](docs/API_CONTRACT.md) |
| [`camera-model-test/`](camera-model-test/) | Python server on the laptop that runs YOLOv8 on camera frames, counts people and sends the result to the backend | [camera-model-test/README.md](camera-model-test/README.md) |
| [`RoomSyncMobile/`](RoomSyncMobile/) | Expo (React Native) phone app that acts as the room camera | [camera-model-test/README.md](camera-model-test/README.md) |

How the pieces connect:

```text
Phone app ──frame every 2.5 s──> inference server ──yes/no + count──> backend ──> dashboard
(RoomSyncMobile)                 (camera-model-test,                  (FastAPI +   (browser,
                                  YOLOv8, port 8001)                   PostgreSQL,  same server)
                                                                       port 8000)
```

---

## Setup on a new Windows laptop

All commands are for **Windows PowerShell**. Do this once per laptop.

### 1. Install the tools

| Tool | Why | Notes |
| --- | --- | --- |
| [Git](https://git-scm.com/download/win) | Get the code | Defaults are fine |
| [Python](https://www.python.org/downloads/windows/) | Backend and camera server | Tick **"Add python.exe to PATH"**. The camera server's YOLO/PyTorch packages can lag behind the newest Python, so if `pip install ultralytics` fails, install Python 3.12 and use `py -3.12 -m venv .venv` in step 5. |
| [PostgreSQL](https://www.postgresql.org/download/windows/) | Database | Remember the password you set for the `postgres` user. Keep port 5432. |
| [Node.js LTS](https://nodejs.org/) | Phone app tools | Defaults are fine |
| **Expo Go** on an Android phone | Runs the phone app | From the Play Store |

If PowerShell refuses to run `Activate.ps1`, run this once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### 2. Get the code

```powershell
cd $HOME\Documents
git clone https://github.com/Sakaido4u/Roomsync.git
cd Roomsync
```

### 3. Create the databases

Open **SQL Shell (psql)** from the Start menu, press Enter for the defaults,
type your `postgres` password, then:

```sql
CREATE DATABASE roomsync;
CREATE DATABASE roomsync_test;
\c roomsync_test
CREATE EXTENSION btree_gist;
```

`roomsync` holds the real data; `roomsync_test` is wiped by the automated
tests every run. Type `\q` to leave.

### 4. Backend and dashboard

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Make two random secrets and paste them into `.env` as `JWT_SECRET` and
`DEVICE_KEY`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET
python -c "import secrets; print(secrets.token_urlsafe(24))"   # DEVICE_KEY
notepad .env
```

In the same file, put your `postgres` password into `DATABASE_URL` and
`TEST_DATABASE_URL`. Then add the demo data, check everything works, and
start the server:

```powershell
python -m app.seed
pytest -q                     # should end with "passed", no failures
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open **http://127.0.0.1:8000/** for the dashboard (and
http://127.0.0.1:8000/docs to try the API by hand). Demo accounts, all with
the password `roomsync123`:

| College ID | Who | Role |
| --- | --- | --- |
| `SA001` | Principal's Office | Super admin |
| `T001` | Dr. K. Rao (HOD) | Admin |
| `T002` | Prof. A. Sharma | Teacher, class teacher of CSE-7A |
| `T003` | Prof. R. Rao | Teacher, class teacher of CSE-5B |
| `1JS23CS044` | Deeptanshu Pandey | Student, CR of CSE-7A |
| `1JS23CS039` | Chirag S | Student |

`--host 0.0.0.0` lets other devices on the same Wi-Fi (a phone, the
projector laptop) open the dashboard at `http://<this laptop's IP>:8000/`.

### 5. Camera server

In a **new** PowerShell window, from the `Roomsync` folder:

```powershell
cd camera-model-test
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install fastapi "uvicorn[standard]" ultralytics opencv-python numpy pytest
Copy-Item .env.example .env
notepad .env       # DEVICE_KEY = exactly the same value as in backend\.env
python -m pytest -q
python -m uvicorn inference_server:app --host 0.0.0.0 --port 8001
```

Check http://127.0.0.1:8001/health shows `{"status":"ready","model":"yolov8n"}`.

### 6. Phone app

Find the laptop's Wi-Fi address with `ipconfig` (**IPv4 Address**, for
example `192.168.1.7`). In a **third** PowerShell window:

```powershell
cd RoomSyncMobile
npm install
npx expo start
```

Scan the QR code with Expo Go. In the app, allow the camera, enter the room
ID **`CSE-101`** and the server **`http://<laptop IP>:8001`**, then tap
**Save and start**. The app remembers both.

The first time Python starts a server, Windows Firewall asks for permission:
allow it on **Private networks** only. The phone and laptop must be on the
same Wi-Fi.

### 7. Email (optional)

Notifications and setup codes are also emailed once a Gmail App Password is
set up; see "Email setup (Gmail)" in [backend/README.md](backend/README.md).
Without it everything works, and setup codes appear in the backend window.

---

## Starting everything (after setup)

Three PowerShell windows, each from the `Roomsync` folder:

```powershell
# 1. Backend + dashboard
cd backend; .\venv\Scripts\Activate.ps1; uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. Camera server
cd camera-model-test; .\.venv\Scripts\Activate.ps1; python -m uvicorn inference_server:app --host 0.0.0.0 --port 8001

# 3. Phone app
cd RoomSyncMobile; npx expo start
```

---

## Demo script

### Before the demo

1. Fresh demo data (deletes everything in the `roomsync` database):

   ```powershell
   cd backend; .\venv\Scripts\Activate.ps1
   python -m app.init_db --reset     # type yes
   python -m app.seed
   ```

2. Make the no-show check fast enough to show live: add these lines to
   `backend\.env` (remove them after the demo):

   ```
   NO_SHOW_REMINDER_AFTER=2
   NO_SHOW_RELEASE_AFTER=1
   ```

3. Start all three parts (see above). Point the phone at the room, room ID
   `CSE-101` (the seeded room with a camera).
4. A browser keeps one login, so open three separate windows and log in:
   **Edge** as `T002` (Prof. Sharma), **Edge InPrivate** as `T003`
   (Prof. Rao), **Chrome** (or a second browser profile) as `T001` (HOD).
   Put the projector on the `T002` window.

### 1. Live people detection

1. In the `T002` window, **Rooms** shows every room for the current hour with
   **"Live · updates every 5 s"**.
2. Point the phone at people. Within a few seconds, **CSE-101** shows
   **"People detected · N"**, and the phone shows **"Synced to RoomSync"**.
3. Point it at an empty wall. After about three frames (7-8 seconds), the tag
   changes to **"Not detected"**. (One odd frame never flips it: the last 3
   counts must agree.)
4. Say: the camera only sends yes/no and a count; no image is stored.

### 2. Booking a room

1. `T002`: **Reserve** → room `CSE-102`, today, a slot later today (for
   example the next full hour), purpose "Extra class - DBMS", class `CSE-7A`
   → **Reserve room**.
2. It appears in **My bookings**, and on **Rooms** for that slot as
   **Reserved** with Prof. Sharma's name and the purpose.

### 3. The "already booked" pop-up

1. `T003`: **Reserve** → the same room and an overlapping time → **Reserve room**.
2. The pop-up shows who booked it (Prof. A. Sharma), when, why, and **free
   rooms at the same time**.
3. Click one of the free rooms: it is booked in one click.

### 4. Admin override with a reason

1. `T001` (HOD): **Rooms** → pick the slot from step 2 → on the **CSE-102**
   card, **Override**.
2. Try to submit without a reason: it is refused. Enter a purpose
   ("Placement briefing") and a reason ("Company visit moved to today") →
   **Override**. The message says who was notified.
3. `T002`: the bell shows **1**. **Notifications** shows "Booking taken over"
   with the HOD's name and the reason. The CR (`1JS23CS044`) gets the class
   version, and both get an email if email is set up.

### 5. No-show reminder

1. `T002`: **Reserve** → `CSE-101`, today, starting about **two minutes from
   now** (a booking cannot start in the past), for 30 minutes, purpose
   "Lab session" → **Reserve room**.
2. Point the phone at an empty corner and keep it running from before the
   start.
3. About 2 minutes after the start (the demo setting), the bell shows a new
   notification: **"Is your room in use?"** with **Keep the room** and
   **Release it**. The CR gets it too.
4. Click **Keep the room**: the booking stays.
   Or show the automatic release: do nothing, and about 1 minute later the
   booking becomes **Released**, both are told, and **Rooms** shows CSE-101
   as **Not booked** again.
5. Say: if the camera stops or its data is patchy, the check does nothing.
   Freeing a room that is actually in use would be worse than keeping an
   empty one.

### 6. Extras if there is time

- **Admin → Timetable**: download the template, upload it, and show
  the clash and skipped-week tables.
- **Admin rights** as `SA001`: make a teacher an admin. The server accepts
  their admin actions at once; their menu shows **Admin** within 30 seconds,
  without logging in again.
- **My class** as `T002`: change the CR of CSE-7A.
- A student (`1JS23CS039`) sees rooms but no booking or admin controls.

---

## Running the tests

| Part | Command | Where |
| --- | --- | --- |
| Backend (uses `roomsync_test`) | `pytest -q` | `backend\`, venv active |
| Camera forwarding | `python -m pytest -q` | `camera-model-test\`, `.venv` active |
| Phone app type check and lint | `npx tsc --noEmit` and `npx expo lint` | `RoomSyncMobile\` |

The backend suite includes a permission sweep that tries every admin and
super-admin action as every other role, logged out, and with forged tokens.

---

## Known limitations

- **Detection accuracy.** YOLOv8n counts people in single frames. Occlusion,
  lighting, camera angle and people far from the camera cause misses or
  extra counts. Smoothing only needs 3 agreeing frames, so a person hidden
  for about 8 seconds can briefly show as "Not detected".
- **The camera is a phone.** Real CCTV access is still pending college
  approval. Rooms can store a camera address, but nothing reads RTSP streams
  yet; the phone app plus the laptop's inference server stand in for a
  camera, one room per phone.
- **Local network only.** Everything is plain HTTP on the college Wi-Fi.
  Frames travel from the phone to the laptop unencrypted, and the
  development servers are not hardened for the internet. Cross-origin
  requests are allowed from anywhere (tighten `allow_origins` in
  `backend/app/main.py` before any real deployment).
- **The no-show check needs steady camera data.** A gap of more than 60
  seconds, an offline camera or no camera means no reminder and no release,
  by design. It only runs for rooms with a camera set.
- **Re-uploading a timetable** rebuilds its future classes: an admin's
  reschedule of a future timetable class is undone (marked cancelled).
  Overrides are kept and appear as skipped weeks.
- **Holidays are not known.** A timetable creates a class every week of the
  semester; holidays have to be removed by an admin.
- **Accounts and classes come from the demo seed.** There is no screen to
  import college ID records, add users or change a class's class teacher.
- **The login limit can be used to lock someone out** for up to 15 minutes by
  typing wrong passwords for their ID. Getting a setup code and setting a new
  password unlocks it.
- **Logins last 8 hours** and are stored in the browser. Logging out clears
  the browser; there is no server-side logout.
- **India time.** All times are India time. The dashboard's "Now" uses the
  computer's clock, so it must be set to India time.
- **Email is best-effort.** Emails are sent after the reply; a failure is
  only written to the backend log. Gmail also limits how many emails a day
  an account may send.
