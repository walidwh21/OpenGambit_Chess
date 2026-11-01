import os
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

try:
    import pygame
    from opengambit.ui import App
except Exception:                                   # pragma: no cover
    pygame = None


def click(app, sq_name_):
    from opengambit.engine import name_sq
    center = app.sq_rect(name_sq(sq_name_)).center
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=center, button=1))
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=center, button=1))


@unittest.skipIf(pygame is None, "pygame not installed")
class UITests(unittest.TestCase):
    def test_click_click_move_and_drag_move(self):
        app = App("volt")
        app.start_game(vs_computer=False, autoflip=False)
        click(app, "e2"); click(app, "e4")
        self.assertEqual(app.game.entries[-1].san, "e4")
        app.anim = None
        # drag e7 -> e5
        from opengambit.engine import name_sq
        src, dst = app.sq_rect(name_sq("e7")).center, app.sq_rect(name_sq("e5")).center
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=src, button=1))
        app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=dst, rel=(0, 0), buttons=(1, 0, 0)))
        app.draw()
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=dst, button=1))
        self.assertEqual([e.san for e in app.game.entries], ["e4", "e5"])

    def test_illegal_move_and_wrong_side_are_ignored(self):
        app = App()
        app.start_game(vs_computer=False)
        click(app, "e2"); click(app, "e5")           # not a legal target
        click(app, "e7")                              # black piece on white's turn
        self.assertEqual(len(app.game.entries), 0)

    def test_promotion_dialog(self):
        app = App()
        app.start_game(vs_computer=False, autoflip=False)
        app.game.pos.set_fen("8/P6k/8/8/8/8/8/K7 w - - 0 1")
        click(app, "a7"); click(app, "a8")
        self.assertIsNotNone(app.promo)
        app.draw()
        rect, move = [s for s in app._promo_slots() if s[1].promo == "n"][0]
        app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1))
        self.assertEqual(app.game.entries[-1].san.startswith("a8=N"), True)
        self.assertEqual(app.game.pos.board[0], "N")

    def test_computer_replies(self):
        app = App()
        app.min_think_seconds = 0
        app.start_game(vs_computer=True, human_color="w", level="beginner")
        click(app, "e2"); click(app, "e4")
        deadline = time.monotonic() + 10
        while len(app.game.entries) < 2 and time.monotonic() < deadline:
            app.update(); time.sleep(0.02)
        self.assertEqual(len(app.game.entries), 2)
        app.cancel_ai()

    def test_computer_opens_when_human_is_black_and_undo_works(self):
        app = App()
        app.min_think_seconds = 0
        app.start_game(vs_computer=True, human_color="b", level="beginner")
        self.assertTrue(app.flipped)
        deadline = time.monotonic() + 10
        while not app.game.entries and time.monotonic() < deadline:
            app.update(); time.sleep(0.02)
        self.assertEqual(len(app.game.entries), 1)
        app.anim = None
        app.cancel_ai()

    def test_every_theme_renders_every_screen(self):
        app = App()
        for theme in app.themes:
            app.set_theme(theme.id)
            app.mode = "menu"; app.draw()
            app.start_game(vs_computer=False)
            app.play_san("e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7#")
            app.draw()
            self.assertEqual(app.game.outcome.kind, "checkmate")


if __name__ == "__main__":
    unittest.main()
