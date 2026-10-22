"""Use the laptop's webcam instead of the phone app.

Does exactly what RoomSyncMobile does: every few seconds it takes one frame,
sends it to the inference server (POST /api/detect) with a room ID, and
shows the people count and whether it reached the RoomSync backend. Handy
for testing the whole chain without a phone.

Frames are only kept in memory and never saved.

Run (camera-model-test\\.venv active, inference server already running):

    python webcam_client.py --room CSE-101

Options: --server http://127.0.0.1:8001  --camera 0  --every 2.5  --no-window
Press q in the preview window (or Ctrl+C) to stop.
"""

import argparse
import base64
import json
import time
import urllib.error
import urllib.request

import cv2


def send_frame(server: str, room_id: str, frame) -> dict:
    """JPEG-encode one frame and ask the inference server to count people."""
    # Same size and quality class as the phone app sends, to keep it quick.
    height, width = frame.shape[:2]
    if width > 960:
        frame = cv2.resize(frame, (960, int(height * 960 / width)))
    ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        raise RuntimeError("Could not encode the camera frame")
    body = json.dumps({
        "room_id": room_id,
        "image_base64": base64.b64encode(jpeg.tobytes()).decode("ascii"),
    }).encode("utf-8")
    request = urllib.request.Request(f"{server}/api/detect", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as reply:
        return json.loads(reply.read())


def describe(result: dict) -> str:
    if result.get("backend_status") == "synced":
        sync = "Synced to RoomSync"
    else:
        sync = f"Not synced: {result.get('backend_error', 'unknown reason')}"
    return f"People: {result['people_count']}  |  {sync}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Send laptop webcam frames to the RoomSync inference server.")
    parser.add_argument("--room", required=True, help="Room ID on the backend, e.g. CSE-101")
    parser.add_argument("--server", default="http://127.0.0.1:8001", help="Inference server address")
    parser.add_argument("--camera", type=int, default=0, help="Webcam number (0 = built-in)")
    parser.add_argument("--every", type=float, default=2.5, help="Seconds between frames")
    parser.add_argument("--no-window", action="store_true", help="Do not show a preview window")
    args = parser.parse_args()
    server = args.server.rstrip("/")

    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        raise SystemExit(f"Could not open webcam {args.camera}. Is another app using it?")

    print(f"Sending webcam {args.camera} to {server} as room {args.room} every {args.every} s. "
          f"Press q in the window or Ctrl+C to stop.")
    status = "Starting..."
    next_send = 0.0
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print("Could not read a frame from the webcam.")
                break

            if time.monotonic() >= next_send:
                next_send = time.monotonic() + args.every
                try:
                    status = describe(send_frame(server, args.room, frame))
                except urllib.error.HTTPError as error:
                    status = f"Inference server replied {error.code}: {error.read().decode('utf-8', 'replace')[:120]}"
                except (urllib.error.URLError, TimeoutError, OSError) as error:
                    status = f"Cannot reach the inference server at {server} ({error})"
                print(time.strftime("%H:%M:%S"), status)

            if not args.no_window:
                preview = frame.copy()
                cv2.rectangle(preview, (0, 0), (preview.shape[1], 44), (0, 0, 0), -1)
                cv2.putText(preview, f"{args.room}  |  {status}"[:90], (12, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.imshow("RoomSync webcam", preview)
                if cv2.waitKey(30) & 0xFF == ord("q"):
                    break
            else:
                time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
