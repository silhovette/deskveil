"""DeskVeil V1 settings. Screen dimensions use Qt logical pixels."""
from pathlib import Path
import sys

CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 360
INFERENCE_FPS = 5
AWAY_CONFIRM_TIME = 2.0
RETURN_CONFIRM_TIME = 0.5
MIN_RETURN_FACE_RATIO = 0.03
MAX_RETURN_CENTER_DISTANCE = 0.35  # frame coordinates, distance from (0.5, 0.5)
MAX_SAMPLE_GAP = 0.8
CAMERA_RETRY_SECONDS = 5
MAX_FACES = 4
VEIL_FADE_MS = 200
GLASS_MAX_EDGE = 960
GLASS_BLUR_SIGMA = 5.0
GLASS_DIM_ALPHA = 105
GLASS_FPS = 30
SNOOZE_MINUTES = 10
PREVIEW_WIDTH = 800
PREVIEW_HEIGHT = 500
PREVIEW_REFRESH_MS = 100


def resource_path(relative):
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / relative


MODEL_PATH = resource_path("models/face_landmarker.task")
