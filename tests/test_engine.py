import random
import unittest

from opengambit.engine import START_FEN, Position, name_sq


class PerftTests(unittest.TestCase):
    CASES = [
        ("start", START_FEN, [20, 400, 8902]),
        ("kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", [48, 2039, 97862]),
        ("en passant / pins", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", [14, 191, 2812, 43238]),
        ("promotions", "n1n5/PPPk4/8/8/8/8/4Kppp/5N1N b - - 0 1", [24, 496, 9483]),
        ("mixed", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", [44, 1486, 62379]),
    ]

    def test_perft(self):
        for name, fen, expected in self.CASES:
            with self.subTest(name):
                pos = Position(fen)
                self.assertEqual([pos.perft(d) for d in range(1, len(expected) + 1)], expected)


class RulesTests(unittest.TestCase):
    def test_fen_round_trip(self):
        for _, fen, _ in PerftTests.CASES:
            self.assertEqual(Position(fen).fen(), fen)

    def test_make_unmake_restores_everything(self):
        rng = random.Random(7)
        for _ in range(20):
            pos = Position()
            before = pos.fen()
            played = 0
            for _ in range(60):
                moves = pos.legal_moves()
                if not moves:
                    break
                pos.make(rng.choice(moves))
                played += 1
            for _ in range(played):
                pos.unmake()
            self.assertEqual(pos.fen(), before)

    def test_fools_mate(self):
        pos = Position()
        for san in ("f3", "e5", "g4", "Qh4#"):
            pos.make(pos.parse_san(san))
        out = pos.outcome()
        self.assertEqual((out.kind, out.winner), ("checkmate", "b"))

    def test_stalemate(self):
        self.assertEqual(Position("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1").outcome().kind, "stalemate")

    def test_insufficient_material(self):
        self.assertEqual(Position("8/8/4k3/8/8/3K4/8/8 w - - 0 1").outcome().kind, "material")
        self.assertEqual(Position("8/8/4k3/8/8/3KB3/8/8 w - - 0 1").outcome().kind, "material")
        self.assertIsNone(Position("8/8/4k3/8/8/3KR3/8/8 w - - 0 1").outcome())

    def test_threefold_repetition(self):
        pos = Position()
        for san in ["Nf3", "Nf6", "Ng1", "Ng8"] * 2:
            pos.make(pos.parse_san(san))
        self.assertEqual(pos.outcome().kind, "repetition")

    def test_fifty_move_rule(self):
        self.assertEqual(Position("8/8/4k3/8/8/3KR3/8/8 w - - 100 80").outcome().kind, "fifty")

    def test_castling_rules(self):
        pos = Position("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        sans = {pos.san(m) for m in pos.legal_moves()}
        self.assertIn("O-O", sans)
        self.assertIn("O-O-O", sans)
        # cannot castle through an attacked square
        pos = Position("r3k2r/8/8/8/8/5r2/8/R3K2R w KQkq - 0 1")
        self.assertNotIn("O-O", {pos.san(m) for m in pos.legal_moves()})

    def test_en_passant_and_promotion_notation(self):
        pos = Position("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3")
        self.assertIn(name_sq("f6"), [m.to for m in pos.legal_moves() if m.frm == name_sq("e5")])
        move = pos.parse_san("exf6")
        pos.make(move)
        self.assertEqual(pos.board[name_sq("f5")], ".")        # captured pawn removed
        promo = Position("8/P6k/8/8/8/8/8/K7 w - - 0 1")
        self.assertEqual(promo.san(promo.parse_san("a8=N")), "a8=N")

    def test_san_disambiguation(self):
        pos = Position("4k3/8/8/8/8/8/4K3/R6R w - - 0 1")
        names = {pos.san(m) for m in pos.legal_moves()}
        self.assertIn("Rad1", names)
        self.assertIn("Rhd1", names)

    def test_bad_move_rejected(self):
        with self.assertRaises(ValueError):
            Position().parse_san("e5")


if __name__ == "__main__":
    unittest.main()
