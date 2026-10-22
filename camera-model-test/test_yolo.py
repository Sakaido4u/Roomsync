
import cv2
from ultralytics import YOLO

# Load pretrained weights; downloads them on first use.
model = YOLO("yolov8n.pt")

# Open the laptop webcam for this initial model test.
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    raise RuntimeError("Could not open webcam")

try:
    while True:
        success, frame = cap.read()

        if not success:
            print("Could not read camera frame")
            break

        # COCO class 0 = person
        results = model.predict(
            source=frame,
            classes=[0],
            conf=0.35,
            imgsz=416,
            verbose=False
        )

        people_count = len(results[0].boxes)

        # Display detections locally for debugging.
        preview = results[0].plot()
        cv2.putText(
            preview,
            f"People: {people_count}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2
        )

        cv2.imshow("RoomSync YOLO Test", preview)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    cap.release()
    cv2.destroyAllWindows()
