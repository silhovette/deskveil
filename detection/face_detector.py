"""peeker's local CPU MediaPipe pipeline, without head pose or identity storage."""
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import config


class FaceDetector:
    def __init__(self):
        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(config.MODEL_PATH),
                                           delegate=python.BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=config.MAX_FACES,
            min_face_detection_confidence=.5,
            min_face_presence_confidence=.5,
            min_tracking_confidence=.5,
            output_facial_transformation_matrixes=False,
            output_face_blendshapes=False,
        )
        self.model = vision.FaceLandmarker.create_from_options(options)
        self.last_timestamp = -1

    def detect(self, frame, now):
        image = mp.Image(image_format=mp.ImageFormat.SRGB,
                         data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        self.last_timestamp = max(self.last_timestamp + 1, int(now * 1000))
        result = self.model.detect_for_video(image, self.last_timestamp)
        boxes = []
        for landmarks in result.face_landmarks:
            xs, ys = [p.x for p in landmarks], [p.y for p in landmarks]
            boxes.append((max(0., min(xs)), max(0., min(ys)),
                          min(1., max(xs)), min(1., max(ys))))
        return boxes

    def close(self):
        self.model.close()
