from __future__ import annotations

import argparse

from .app_settings import load_and_sync_settings
from .config import DEFAULT_RESOLUTION
from .gopro_streamer import GoProStreamer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GoPro Hero 9 / 10 / 11 / 12 Streaming Tool pour OBS")
    parser.add_argument("--res", type=int, choices=[720, 1080], default=DEFAULT_RESOLUTION, help="720 ou 1080")
    view_group = parser.add_mutually_exclusive_group()
    view_group.add_argument("--view", dest="view", action="store_true", help="Afficher un aperçu local")
    view_group.add_argument("--no-view", dest="view", action="store_false", help="Désactiver l'aperçu local")
    parser.set_defaults(view=None)
    parser.add_argument("-c", "--chrono", action="store_true", help="Afficher un chronomètre sur le flux")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = load_and_sync_settings()
    streamer = GoProStreamer(
        res=args.res,
        show_preview=settings.launch_with_view if args.view is None else args.view,
        show_chrono=args.chrono,
        settings=settings,
    )
    streamer.start()


if __name__ == "__main__":
    main()