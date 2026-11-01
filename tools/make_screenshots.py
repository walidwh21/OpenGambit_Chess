"""Render real screenshots of the running UI, headlessly.

    python tools/make_screenshots.py [output_dir]

Everything is drawn by the actual application code (no mock-ups), so the images
always match what a player would see.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame  # noqa: E402

from opengambit.engine import name_sq  # noqa: E402
from opengambit.ui import App, WIN_H, WIN_W  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

ITALIAN = "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d4 exd4 cxd4 Bb4+ Nc3 Nxe4 O-O Bxc3 d5 Bf6 Re1 Ne7".split()


def silent_moves(app, tokens):
    """Play moves without triggering the computer (screenshots must be deterministic)."""
    for token in tokens:
        app.game.play(app.game.pos.parse_san(token))
    app.after_move()


def shot(app, name):
    app.min_think_seconds = 10 ** 6          # never let a background AI move land mid-capture
    app.draw()
    path = OUT / name
    pygame.image.save(app.screen, str(path))
    print("wrote", path.name)
    return app.screen.copy()


def main():
    app = App("classic")

    # 1-2: menus (dark and light theme, both modes)
    shot(app, "01_menu_classic.png")
    app.set_theme("prism")
    app.menu.update(mode="two", autoflip=True)
    shot(app, "02_menu_two_players_prism.png")

    # 3: new game against the computer
    app.set_theme("classic")
    app.start_game(vs_computer=True, human_color="w", level="club")
    app.cancel_ai()
    shot(app, "03_new_game_classic.png")

    # 4: middlegame with legal-move hints (Tesla-inspired palette)
    app.set_theme("volt")
    app.start_game(vs_computer=False, autoflip=False)
    silent_moves(app, ITALIAN)
    app.select_square("e1")
    shot(app, "04_midgame_hints_volt.png")

    # 5: check (Google-inspired light palette)
    app.set_theme("prism")
    app.start_game(vs_computer=False, autoflip=False)
    silent_moves(app, "e4 e5 Nf3 Nc6 Bb5 a6 Bxc6 dxc6 Nxe5 Qd4 Nf3 Qxe4+".split())
    shot(app, "05_check_prism.png")

    # 6: promotion picker (Netflix-inspired palette)
    app.set_theme("reel")
    app.start_game(vs_computer=False, autoflip=False)
    app.game.pos.set_fen("r3k2r/1P4pp/8/8/8/8/6PP/4K3 w kq - 0 1")
    app.select_square("b7")
    app.try_move(name_sq("b7"), name_sq("b8"), animate=False)
    shot(app, "06_promotion_reel.png")

    # 7: checkmate (Spotify-inspired palette)
    app.set_theme("groove")
    app.start_game(vs_computer=False, autoflip=False)
    silent_moves(app, "e4 e5 Qh5 Nc6 Bc4 Nf6 Qxf7#".split())
    shot(app, "07_checkmate_groove.png")
    app.banner_dismissed = True                  # same position with the banner hidden
    shot(app, "07b_checkmate_board_groove.png")

    # 8: computer thinking, playing Black on a flipped board (Midnight)
    app.set_theme("midnight")
    app.start_game(vs_computer=True, human_color="b", level="expert")
    app.cancel_ai()
    app.game.vs_computer = False                 # silent set-up moves for both sides
    silent_moves(app, ITALIAN[:8])
    app.game.vs_computer = True
    app.cancel_ai()
    app.flipped = True
    shot(app, "08_computer_thinking_midnight.png")
    app.cancel_ai()

    # 9: theme gallery, same position in every theme
    scale, cap_h, gap = 0.5, 34, 16
    cell_w, cell_h = int(WIN_W * scale), int(WIN_H * scale)
    cols = 3
    rows = (len(app.themes) + cols - 1) // cols
    sheet = pygame.Surface((cols * cell_w + (cols + 1) * gap, rows * (cell_h + cap_h) + (rows + 1) * gap))
    sheet.fill((21, 22, 26))
    for i, theme in enumerate(app.themes):
        app.set_theme(theme.id)
        app.start_game(vs_computer=False, autoflip=False)
        silent_moves(app, ITALIAN)
        app.select_square("e1")
        app.min_think_seconds = 10 ** 6
        app.draw()
        small = pygame.transform.smoothscale(app.screen, (cell_w, cell_h))
        x = gap + (i % cols) * (cell_w + gap)
        y = gap + (i // cols) * (cell_h + cap_h + gap)
        sheet.blit(small, (x, y))
        label = f"{theme.name}  \u00b7  {theme.subtitle}"
        img = app.font(15, True).render(label, True, (225, 225, 230))
        sheet.blit(img, (x, y + cell_h + 8))
    pygame.image.save(sheet, str(OUT / "09_theme_gallery.png"))
    print("wrote 09_theme_gallery.png")


if __name__ == "__main__":
    main()
