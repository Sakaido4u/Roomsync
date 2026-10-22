
import base64
import binascii
import os
from datetime import datetime, timezone
from threading import Lock

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from ultralytics import YOLO

app = FastAPI(title="RoomSync Local YOLO Inference")

# Load the model once when the server starts.
model = YOLO("yolov8n.pt")
model_lock = Lock()

MAX_IMAGE_BYTES = 2_000_000


class FrameRequest(BaseModel):
    image_base64: str = Field(min_length=1)
    room_id: str = Field(default="CSE-101", max_length=50)


@app.get("/health")
def health():
    return {"status": "ready", "model": "yolov8n"}


@app.post("/api/detect")
def detect_people(payload: FrameRequest):
    encoded = payload.image_base64

    # Accept either raw base64 or a data URI.
    if encoded.startswith("data:"):
        parts = encoded.split(",", 1)
        if len(parts) != 2:
            raise HTTPException(400, "Invalid image data URI")
        encoded = parts[1]

    # Reject excessively large frames before decoding.
    if len(encoded) > (MAX_IMAGE_BYTES * 4 // 3 + 8):
        raise HTTPException(413, "Image is too large")

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Invalid base64 image")

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image is too large")

    # Decode the image into memory; do not write it to disk.
    buffer = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)

    if frame is None:
        raise HTTPException(400, "Could not decode image")

    try:
        # Serialize access to the model for this prototype.
        with model_lock:
            results = model.predict(
                source=frame,
                classes=[0],  # COCO class 0 = person
                conf=0.35,
                imgsz=416,
                verbose=False,
            )

            people_count = len(results[0].boxes)

        return {
            "room_id": payload.room_id,
            "people_count": people_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        # Release references; never save the image or detections.
        del frame
        del buffer
        del image_bytes
