GOPRO_IP = "172.24.105.51"
STREAM_URL = "udp://@0.0.0.0:8554?overrun_nonfatal=1&fifo_size=1000000"

FFMPEG_CAPTURE_OPTIONS = "fflags;nobuffer|flags;low_delay|max_delay;0|probesize;32|analyzeduration;0"

FOV_MAP = {
    "wide": 0,
    "narrow": 1,
    "superview": 2,
    "linear": 4,
}

DEFAULT_RESOLUTION = 720
DEFAULT_FPS = 30
DEFAULT_FOV = "superview"