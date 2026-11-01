"""Command line entry point:  python -m opengambit [options]"""
from __future__ import annotations

import argparse

from . import __version__
from .ai import LEVELS
from .themes import load_themes


def main(argv=None) -> int:
    themes = [t.id for t in load_themes()]
    parser = argparse.ArgumentParser(prog="opengambit", description="A themeable chess game.")
    parser.add_argument("--theme", choices=themes, default=themes[0], help="colour theme")
    parser.add_argument("--level", choices=list(LEVELS), default="casual", help="computer strength")
    parser.add_argument("--color", choices=["white", "black", "random"], default="white",
                        help="the side you play against the computer")
    parser.add_argument("--two-player", action="store_true", help="two humans, one screen")
    parser.add_argument("--play", action="store_true", help="skip the menu and start immediately")
    parser.add_argument("--list-themes", action="store_true", help="print available themes and exit")
    parser.add_argument("--version", action="version", version=f"opengambit {__version__}")
    args = parser.parse_args(argv)

    if args.list_themes:
        for t in load_themes():
            print(f"{t.id:10s} {t.name:10s} {t.subtitle}")
        return 0

    from .ui import App                         # import pygame lazily (keeps --help fast)
    app = App(theme_id=args.theme)
    app.menu.update(mode="two" if args.two_player else "ai", level=args.level,
                    color={"white": "w", "black": "b", "random": "r"}[args.color])
    if args.play:
        app._start_from_menu()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
