# RoomSync Camera Module

RoomSync's camera module uses an Expo React Native app and a local Python FastAPI server running YOLOv8 to estimate the number of people visible in a camera frame, and sends the result to the RoomSync backend so the room status grid shows it live.

## How it works

1. The mobile app captures a frame approximately every 2.5 seconds.
2. It sends the frame as Base64 to the inference server on your laptop (port **8001**).
3. The server runs YOLOv8 person detection and counts the people.
4. The server sends only yes/no and the count to the RoomSync backend (`POST /api/occupancy` on port **8000**), using the device key from `camera-model-test/.env`. The phone never sees the key.
5. The app shows the latest count and whether it reached the backend ("Synced to RoomSync" or "Not synced: <reason>").

To stop the room flickering between "people detected" and "not detected" because of one bad frame, the server only changes its yes/no answer for a room when the last 3 counts agree. If the backend refuses a reading or cannot be reached, the server still returns the count to the phone, and waits 10 seconds before trying that room again.

> **Privacy note:** Frames are sent over your local network to the laptop for counting. The inference server decodes them in memory and never stores them. The RoomSync backend only receives yes/no and a head count, never an image. The app deletes each temporary photo file on the phone after the request. Use this prototype only on a trusted network.

## Project layout

```text
Roomsync/
├── RoomSyncMobile/       # Expo / React Native mobile app
│   └── src/
│       ├── app/
│       │   └── index.tsx           # Camera screen
│       └── lib/
│           └── camera-settings.ts  # Saved room ID and server address
├── backend/              # RoomSync FastAPI backend
├── docs/                 # API contract
└── camera-model-test/    # Python YOLO inference server
    ├── README.md         # This file
    ├── inference_server.py
    ├── backend_sync.py   # Smoothing and sending readings to the backend
    ├── .env.example      # Copy to .env: backend address and device key
    ├── tests/            # Automated tests for backend_sync.py
    ├── webcam_client.py  # Use the laptop webcam instead of the phone
    ├── test_yolo.py      # Optional standalone webcam test
    └── yolov8n.pt        # YOLOv8 nano model weights
```

## Requirements

- Python 3.10 or newer recommended
- Node.js LTS and npm
- Android phone with Expo Go installed
- Laptop and phone connected to the same Wi-Fi network
- Git installed
- YOLO weights file `yolov8n.pt` available in `camera-model-test/`
- The RoomSync backend set up as in [`backend/README.md`](../backend/README.md)

Use the existing `package.json` and lockfile rather than upgrading dependencies unnecessarily.

## 1. Start the backend

In a PowerShell window, from the repository root:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Keep this terminal open. The room you will point the camera at must exist on the backend (the demo data from `python -m app.seed` includes `CSE-101`).

## 2. Start the Python inference server

Open a second PowerShell window and, from the repository root, move to this folder:

```powershell
cd camera-model-test
```

Create and activate a virtual environment (recommended):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the Python dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install fastapi "uvicorn[standard]" ultralytics opencv-python numpy pytest
```

Make sure `yolov8n.pt` is in this directory. Ultralytics may download the pretrained weights when the model initializes if the file is absent; this requires internet access.

Create your `.env` file from the example:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set `DEVICE_KEY` to exactly the same value as `DEVICE_KEY` in `backend/.env`. Keep `BACKEND_URL=http://127.0.0.1:8000` when the backend runs on the same laptop. Never commit `.env`.

Start the server on port **8001** (the backend uses 8000):

```powershell
python -m uvicorn inference_server:app --host 0.0.0.0 --port 8001
```

Keep this terminal open. Test the server on your laptop by opening:

```text
http://127.0.0.1:8001/health
```

Expected response:

```json
{"status":"ready","model":"yolov8n"}
```

## 3. Find the laptop's IP address

In another PowerShell window, run:

```powershell
ipconfig
```

Under the active Wi-Fi adapter, find **IPv4 Address**. The phone app must use this address, not `127.0.0.1`. You will type it into the app in step 5, for example `http://192.168.1.7:8001`.

To change the address the app starts with, edit this constant in `RoomSyncMobile/src/lib/camera-settings.ts`:

```ts
export const DEFAULT_SERVER_URL = 'http://192.168.1.7:8001';
```

If the phone cannot connect, confirm both devices are on the same Wi-Fi network and allow Python/port 8001 through Windows Firewall on **Private networks only**. Do not expose this development server directly to the public internet.

## 4. Start the Expo app

Open another terminal and, from the repository root:

```powershell
cd RoomSyncMobile
npm install
npx expo start
```

Scan the QR code with Expo Go. If LAN discovery fails, try:

```powershell
npx expo start --tunnel
```

Note: an Expo tunnel does not automatically expose the local YOLO API; the phone still needs network access to your laptop's server.

## 5. Use the app

1. Grant camera permission.
2. Enter the **room ID** (for example `CSE-101`) and the **inference server** address from step 3, then tap **Save and start**. Both are remembered the next time the app opens; tap **Change room or server** to edit them.
3. Point the camera at the area to count.
4. Wait for the people count and the sync line to update. "Synced to RoomSync" means the backend received the reading.
5. Use the camera switch button to change between front and rear cameras.

The count is an estimate from individual frames. Occlusion, lighting, camera angle, and model confidence can affect accuracy.

## Using the laptop webcam instead of the phone

For testing without a phone, `webcam_client.py` does what the app does:
it sends a webcam frame to the inference server every 2.5 seconds with a
room ID, and shows the count and sync status in a preview window. Frames
stay in memory and are never saved. With the backend and the inference
server running, in another window (`.venv` active, inside
`camera-model-test/`):

```powershell
python webcam_client.py --room CSE-101
```

Press **q** in the preview window to stop. Options: `--server`, `--camera`
(another webcam number), `--every` (seconds), `--no-window`.

`test_yolo.py` is a simpler check: it only shows the webcam with people
boxes and a count, without the inference server or the backend.

## End-to-end check

Do this once everything above is running, to confirm the whole chain works: phone → inference server → backend → room status grid.

1. In the app, set the room to `CSE-101` and point the phone at one or more people. Wait until the app shows a count above 0 and **Synced to RoomSync**.
2. On the laptop, open http://127.0.0.1:8000/docs.
3. Log in: `POST /api/auth/login` → **Try it out** → `{"college_id": "T002", "password": "roomsync123"}` → **Execute**. Copy the `token`, click **Authorize** at the top of the page, paste it, **Authorize**.
4. Open `GET /api/rooms/status` → **Try it out**. Enter today's date (for example `2026-11-03`), and a `start` and `end` around the current time (for example `15:00` and `16:00`) → **Execute**.
5. In the reply, find `CSE-101`. You should see `"occupancy": "people_detected"` and a `head_count`.
6. Point the phone at an empty area. After about three frames (7–8 seconds) the app should still say "Synced", and running step 4 again should show `"occupancy": "not_detected"` with `"head_count": 0`.
7. Stop the inference server (Ctrl+C). About a minute later, step 4 shows `"occupancy": "no_data"`, because the backend treats readings older than 60 seconds as stale.

## Automated tests

The forwarding logic in `backend_sync.py` has tests that use a fake backend, so no camera, YOLO model or running backend is needed. With the `.venv` active, inside `camera-model-test/`:

```powershell
python -m pytest -v
```

## Troubleshooting

### The count stays blank or requests fail

- Check that `http://127.0.0.1:8001/health` works on the laptop.
- Check the server address in the app uses the laptop's current IPv4 address and port 8001.
- Confirm the phone and laptop are on the same Wi-Fi network.
- Check Windows Firewall for the Python server on the private network.
- Check the Python server terminal for errors.

### The app says "Not synced: ..."

The count worked, but the backend did not accept it. The reason tells you why:

- **backend unreachable**: the backend is not running, or `BACKEND_URL` in `camera-model-test/.env` is wrong.
- **backend refused the device key**: `DEVICE_KEY` in `camera-model-test/.env` does not match `backend/.env`. Restart the inference server after editing `.env`.
- **DEVICE_KEY is not set**: `camera-model-test/.env` is missing or has an empty `DEVICE_KEY`.
- **room ... does not exist on the backend**: fix the room ID in the app, or add the room on the backend.
- **time is in the future**: the laptop's clock is wrong.

After a failure the server waits 10 seconds before trying that room again, so a fix can take a few seconds to show.

### Python modules are missing

Activate the virtual environment and install the dependencies listed above.

### `yolov8n.pt` is missing

Place the model weights in `camera-model-test/`, or allow Ultralytics to download them on first run with internet access.

### Expo dependency errors

Run commands from `RoomSyncMobile/` and preserve the Expo SDK and package versions already configured in the project. Avoid upgrading Expo packages individually unless intentionally upgrading the SDK.
