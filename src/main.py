from __future__ import annotations

import argparse

from .config import DEFAULT_FPS, DEFAULT_FOV, DEFAULT_RESOLUTION
from .gopro_streamer import GoProStreamer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GoPro Hero 9 / 10 / 11 / 12 Streaming Tool pour OBS")
    parser.add_argument("--res", type=int, choices=[720, 1080], default=DEFAULT_RESOLUTION, help="720 ou 1080")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help="Frames par seconde")
    parser.add_argument("--fov", type=str, choices=["wide", "narrow", "superview", "linear"], default=DEFAULT_FOV, help="Lentille")
    parser.add_argument("--view", action="store_true", help="Afficher la fenêtre")
    parser.add_argument("-c", "--chrono", action="store_true", help="Afficher un chronomètre sur le flux")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    streamer = GoProStreamer(
        res=args.res,
        fov=args.fov,
        fps=args.fps,
        show_preview=args.view,
        show_chrono=args.chrono,
    )
    streamer.start()


if __name__ == "__main__":
    main()