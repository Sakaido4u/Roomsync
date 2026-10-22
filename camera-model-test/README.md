# RoomSync Camera Module

RoomSync's camera module uses an Expo React Native app and a local Python FastAPI server running YOLOv8 to estimate the number of people visible in a camera frame.

## How it works

1. The mobile app captures a frame approximately every 2.5 seconds.
2. It sends the frame as Base64 to the inference server on your laptop.
3. The server runs YOLOv8 person detection and returns a people count.
4. The app displays the latest count and lets you switch between front and rear cameras.

> **Privacy note:** Frames are sent over your local network to the laptop for inference. The app attempts to delete each temporary photo file after the request, but this does not guarantee image data never touches storage. Use this prototype only on a trusted network.

## Project layout

```text
Roomsync/
├── README.md
├── RoomSyncMobile/       # Expo / React Native mobile app
│   └── app/
│       └── index.tsx
└── camera-model-test/    # Python YOLO inference server
    ├── inference_server.py
    ├── test_yolo.py      # Optional standalone webcam test, if present
    └── yolov8n.pt        # Model weights (downloaded or provided separately)
```

## Requirements

- Python 3.10 or newer recommended
- Node.js LTS and npm
- Android phone with Expo Go installed
- Laptop and phone connected to the same Wi-Fi network
- Git installed
- YOLO weights file `yolov8n.pt` available in `camera-model-test/`

Use the existing `package.json` and lockfile rather than upgrading dependencies unnecessarily.

## 1. Start the Python inference server

Open PowerShell and move to the Python folder. Example path:

```powershell
cd "C:\Users\dhanv\Downloads\roomsync-expo-camera-starter\Roomsync\camera-model-test"
```

Create and activate a virtual environment (recommended):

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the Python dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install fastapi "uvicorn[standard]" ultralytics opencv-python numpy
```

Make sure `yolov8n.pt` is in this directory. Ultralytics may download the pretrained weights when the model initializes if the file is absent; this requires internet access.

Start the server:

```powershell
python -m uvicorn inference_server:app --host 0.0.0.0 --port 8000
```

Keep this terminal open. Test the server on your laptop by opening:

```text
http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ready","model":"yolov8n"}
```

## 2. Set the laptop's IP address

In another PowerShell window, run:

```powershell
ipconfig
```

Under the active Wi-Fi adapter, find **IPv4 Address**. The phone app must use this address, not `127.0.0.1`.

Open `RoomSyncMobile/app/index.tsx` and update this line to match your current laptop IPv4 address:

```tsx
const API_URL = 'http://192.168.1.7:8000/api/detect';
```

Replace `192.168.1.7` if your IP address is different.

If the phone cannot connect, confirm both devices are on the same Wi-Fi network and allow Python/port 8000 through Windows Firewall on **Private networks only**. Do not expose this development server directly to the public internet.

## 3. Start the Expo app

Open a second terminal:

```powershell
cd "C:\Users\dhanv\Downloads\roomsync-expo-camera-starter\Roomsync\RoomSyncMobile"
npm install
npx expo start
```

Scan the QR code with Expo Go. If LAN discovery fails, try:

```powershell
npx expo start --tunnel
```

Note: an Expo tunnel does not automatically expose the local YOLO API; the phone still needs network access to your laptop's server.

## 4. Use the app

1. Grant camera permission.
2. Keep the Python inference server running.
3. Point the camera at the area to count.
4. Wait for the status and people count to update.
5. Use the camera switch button to change between front and rear cameras.

The count is an estimate from individual frames. Occlusion, lighting, camera angle, and model confidence can affect accuracy.

## Troubleshooting

### The count stays blank or requests fail

- Check that `http://127.0.0.1:8000/health` works on the laptop.
- Check `API_URL` uses the laptop's current IPv4 address.
- Confirm the phone and laptop are on the same Wi-Fi network.
- Check Windows Firewall for the Python server on the private network.
- Check the Python server terminal for errors.

### Python modules are missing

Activate the virtual environment and install the dependencies listed above.

### `yolov8n.pt` is missing

Place the model weights in `camera-model-test/`, or allow Ultralytics to download them on first run with internet access.

### Expo dependency errors

Run commands from `RoomSyncMobile/` and preserve the Expo SDK and package versions already configured in the project. Avoid upgrading Expo packages individually unless intentionally upgrading the SDK.

## Push to GitHub branch `feature/camera-module`

Run Git commands from the **repository root**, not inside `RoomSyncMobile/` or `camera-model-test/`:

```powershell
cd "C:\Users\dhanv\Downloads\roomsync-expo-camera-starter\Roomsync"
git status
git branch --show-current
```

If you are not on the requested branch, switch to it:

```powershell
git switch feature/camera-module
```

If the branch exists only on the remote, use:

```powershell
git switch --track origin/feature/camera-module
```

Before staging, check that you are not committing virtual environments, `node_modules`, API keys, caches, or unwanted large generated files. The `yolov8n.pt` weights can be large; follow the repository's existing conventions before adding them.

If needed, add or update `.gitignore` in the repository root:

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
venv/

# Node / Expo
node_modules/
.expo/
dist/
web-build/

# Local secrets and editor files
.env
.env.*
!.env.example
.vscode/
.DS_Store
```

Then stage, commit, and push:

```powershell
git status
git add README.md RoomSyncMobile camera-model-test
git status
git commit -m "Add RoomSync camera module"
git push -u origin feature/camera-module
```

Review the staged files shown by `git status` before committing. If you saved this README somewhere other than the repository root, copy it there and name it `README.md` first.

If Git rejects the push because the branch has diverged, do not force-push. Inspect `git status` and `git log --oneline --decorate -5` before deciding how to reconcile the branches.

## Verify the push

Open the repository on GitHub, select the `feature/camera-module` branch, and confirm the README, mobile app, and Python server files are present.
