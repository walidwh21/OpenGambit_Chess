import random
import time
import unittest

from opengambit.ai import LEVELS, Level, Searcher, evaluate
from opengambit.book import OpeningBook
from opengambit.engine import START_FEN, Position
from opengambit.game import Game
from opengambit.themes import REQUIRED_COLORS, load_themes


class EvaluationTests(unittest.TestCase):
    def test_start_position_is_balanced(self):
        self.assertEqual(evaluate(Position()), 0)

    def test_material_matters(self):
        up_a_queen = Position("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        self.assertGreater(evaluate(up_a_queen), 800)

    def test_symmetry(self):
        white = Position("4k3/8/8/8/8/8/PP6/4K3 w - - 0 1")
        black = Position("4k3/pp6/8/8/8/8/8/4K3 b - - 0 1")
        self.assertEqual(evaluate(white), -evaluate(black))


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.searcher = Searcher(book=None, rng=random.Random(3))

    def test_finds_mate_in_one(self):
        pos = Position("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
        self.assertEqual(pos.san(self.searcher.choose(pos, LEVELS["casual"])), "Qxf7#")

    def test_finds_back_rank_mate(self):
        pos = Position("6k1/5ppp/8/8/8/8/5PPP/R3R1K1 w - - 0 1")
        self.assertEqual(pos.san(self.searcher.choose(pos, LEVELS["club"])), "Ra8#")

    def test_takes_free_queen(self):
        pos = Position("rnb1kbnr/pppp1ppp/8/4p3/4P2q/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
        self.assertEqual(pos.san(self.searcher.choose(pos, LEVELS["club"])), "Nxh4")

    def test_every_level_returns_a_legal_move_quickly(self):
        pos = Position("r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7")
        for key in ("beginner", "casual"):
            start = time.monotonic()
            move = self.searcher.choose(pos, LEVELS[key])
            self.assertIn(move, pos.legal_moves())
            self.assertLess(time.monotonic() - start, 5)

    def test_time_budget_is_respected(self):
        pos = Position("r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7")
        start = time.monotonic()
        self.searcher.choose(pos, Level("t", "t", 10, 0.6, 0, False))
        self.assertLess(time.monotonic() - start, 2.0)

    def test_search_does_not_mutate_input(self):
        pos = Position()
        before = pos.fen()
        self.searcher.choose(pos, LEVELS["casual"])
        self.assertEqual(pos.fen(), before)

    def test_no_moves_returns_none(self):
        pos = Position("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        self.assertIsNone(self.searcher.choose(pos, LEVELS["casual"]))


class BookTests(unittest.TestCase):
    def test_all_lines_load_and_name_positions(self):
        book = OpeningBook.load()
        self.assertGreater(len(book), 100)
        pos = Position()
        for san in "e4 e5 Nf3 Nc6 Bb5".split():
            pos.make(pos.parse_san(san))
        self.assertEqual(book.name_for(pos), "Ruy Lopez")

    def test_book_moves_are_legal(self):
        book = OpeningBook.load()
        pos = Position()
        for _ in range(6):
            move = book.pick(pos, random.Random(1))
            if move is None:
                break
            self.assertIn(move, pos.legal_moves())
            pos.make(move)


class ThemeTests(unittest.TestCase):
    def test_themes_are_complete_and_unique(self):
        themes = load_themes()
        self.assertGreaterEqual(len(themes), 6)
        self.assertEqual(len({t.id for t in themes}), len(themes))
        for t in themes:
            for key in REQUIRED_COLORS:
                self.assertIn(key, t.colors)
            self.assertNotEqual(t.light_sq, t.dark_sq)
            self.assertNotEqual(t.white_fill, t.black_fill)


class GameTests(unittest.TestCase):
    def test_play_capture_undo(self):
        g = Game(vs_computer=False)
        for san in ("e4", "d5", "exd5"):
            g.play(g.pos.parse_san(san))
        self.assertEqual(g.captured_by("w"), ["p"])
        self.assertEqual(g.material_balance(), 1)
        self.assertEqual(g.move_pairs()[1], (2, "exd5", None))
        g.undo(1)
        self.assertEqual(g.captured_by("w"), [])
        self.assertEqual(len(g.entries), 2)

    def test_undo_to_human_against_computer(self):
        g = Game(vs_computer=True, human_color="w")
        g.play(g.pos.parse_san("e4"))
        g.play(g.pos.parse_san("e5"))
        g.undo_to_human()
        self.assertEqual((len(g.entries), g.turn), (0, "w"))


if __name__ == "__main__":
    unittest.main()
