GOPRO_IP = "172.24.105.51"
STREAM_URL = "udp://@0.0.0.0:8554?overrun_nonfatal=1&fifo_size=1000000"
NETWORK_STREAM_PORT = 8765
NETWORK_STREAM_PATH = "stream.mjpg"

FFMPEG_CAPTURE_OPTIONS = "fflags;nobuffer|flags;low_delay|max_delay;0|probesize;32|analyzeduration;0"

DEFAULT_RESOLUTION = 720
DEFAULT_FPS = 30
