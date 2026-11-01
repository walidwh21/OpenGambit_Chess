"""Computer opponent: evaluation + iterative-deepening alpha-beta search.

Techniques used
---------------
* negamax alpha-beta with a transposition table
* iterative deepening under a wall-clock budget
* move ordering (hash move, MVV-LVA captures, promotions, killer moves)
* quiescence search so the engine doesn't stop in the middle of a capture chain
* check extensions
* tapered evaluation (middlegame <-> endgame) with generated piece-square tables
* optional "human-like" randomness for the easier levels
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .book import OpeningBook
from .engine import BLACK, WHITE, Move, Position

INF = 10 ** 6
MATE = 100_000
VALUE = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}


# --------------------------------------------------------------------------
# Difficulty levels
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Level:
    key: str
    name: str
    max_depth: int
    seconds: float
    margin: int          # centipawns of randomness (0 = always play the best move)
    use_book: bool = True


LEVELS: Dict[str, Level] = {lv.key: lv for lv in (
    Level("beginner", "Beginner", 1, 0.5, 120, use_book=False),
    Level("casual",   "Casual",   2, 1.5, 35),
    Level("club",     "Club",     4, 3.0, 0),
    Level("expert",   "Expert",   6, 8.0, 0),
)}


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------
def _build_tables():
    """Piece-square tables generated from simple positional rules.

    Index = row * 8 + col from White's point of view (row 7 is White's back rank).
    """
    mg = {k: [0] * 64 for k in "PNBRQK"}
    eg = {k: [0] * 64 for k in "PNBRQK"}
    for r in range(8):
        for c in range(8):
            i = r * 8 + c
            cent = min(r, 7 - r) + min(c, 7 - c)           # 0 (corner) .. 6 (centre)
            adv = 6 - r                                      # pawn progress 0..5
            long_diag = 6 if (r == c or r + c == 7) else 0
            if 0 < r < 7:
                mg["P"][i] = 4 * adv + (10 if c in (3, 4) and adv >= 1 else 0) - (6 if c in (0, 7) else 0)
                eg["P"][i] = 9 * adv
            mg["N"][i] = eg["N"][i] = 7 * cent - 30
            mg["B"][i] = eg["B"][i] = 4 * cent - 14 + long_diag
            mg["R"][i] = eg["R"][i] = (15 if r == 1 else 0) + (3 if c in (3, 4) else 0)
            mg["Q"][i] = eg["Q"][i] = 2 * cent - 6
            mg["K"][i] = -18 * (7 - r) + (14 if c in (1, 2, 6) else 0) - (10 if c in (3, 4) else 0)
            eg["K"][i] = 10 * cent - 20
    return mg, eg


_MG, _EG = _build_tables()
_PASSED_BONUS = (0, 5, 10, 20, 35, 60, 90, 0)


def _mirror(i: int) -> int:
    return (7 - (i >> 3)) * 8 + (i & 7)


def evaluate(pos: Position) -> int:
    """Static score in centipawns from White's point of view."""
    board = pos.board
    mg = eg = 0
    material_left = 0
    bishops = {"B": 0, "b": 0}
    pawn_files = {"P": [0] * 8, "p": [0] * 8}
    pawns = {"P": [], "p": []}

    for i, p in enumerate(board):
        if p == ".":
            continue
        kind = p.upper()
        white = p.isupper()
        idx = i if white else _mirror(i)
        sign = 1 if white else -1
        base = VALUE[kind]
        mg += sign * (base + _MG[kind][idx])
        eg += sign * (base + _EG[kind][idx])
        if kind not in "PK":
            material_left += base
        if kind == "B":
            bishops[p] += 1
        elif kind == "P":
            pawn_files[p][i & 7] += 1
            pawns[p].append(i)

    score_pawns = 0
    for pawn, sign in (("P", 1), ("p", -1)):
        files = pawn_files[pawn]
        enemy = "p" if pawn == "P" else "P"
        enemy_files_pawns = pawns[enemy]
        for f in range(8):
            if files[f] > 1:
                score_pawns -= sign * 12 * (files[f] - 1)                      # doubled
            if files[f] and not (f > 0 and files[f - 1]) and not (f < 7 and files[f + 1]):
                score_pawns -= sign * 14 * files[f]                            # isolated
        for sq in pawns[pawn]:                                                 # passed pawns
            r, c = sq >> 3, sq & 7
            blocked = False
            for e in enemy_files_pawns:
                er, ec = e >> 3, e & 7
                if abs(ec - c) <= 1 and ((er < r) if pawn == "P" else (er > r)):
                    blocked = True
                    break
            if not blocked:
                progress = 6 - r if pawn == "P" else r - 1
                score_pawns += sign * _PASSED_BONUS[max(0, min(7, progress))]

    pair = (30 if bishops["B"] >= 2 else 0) - (30 if bishops["b"] >= 2 else 0)
    phase = min(1.0, material_left / 6400.0)
    return int(mg * phase + eg * (1.0 - phase)) + score_pawns + pair


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------
class SearchTimeout(Exception):
    pass


_EXACT, _LOWER, _UPPER = 0, 1, 2


class Searcher:
    def __init__(self, book: Optional[OpeningBook] = None,
                 rng: Optional[random.Random] = None) -> None:
        self.book = book
        self.rng = rng or random.Random()
        self.tt: Dict[str, Tuple[int, int, int, Optional[Move]]] = {}
        self.killers: Dict[int, List[Move]] = {}
        self.nodes = 0
        self._deadline = 0.0
        self._stop: Optional[threading.Event] = None
        self._best_prev: Optional[Move] = None

    # ------------------------------------------------------------ public
    def choose(self, position: Position, level: Level,
               stop: Optional[threading.Event] = None) -> Optional[Move]:
        """Pick a move for the side to move. Never mutates ``position``."""
        pos = position.copy()
        moves = pos.legal_moves()
        if not moves:
            return None
        if len(moves) == 1:
            return moves[0]
        if level.use_book and self.book:
            booked = self.book.pick(pos, self.rng)
            if booked is not None and booked in moves:
                return booked

        if len(self.tt) > 400_000:
            self.tt.clear()
        self.killers.clear()
        self.nodes = 0
        self._stop = stop
        self._deadline = time.monotonic() + level.seconds
        self._best_prev = None
        best = moves[0]
        last_scored: List[Tuple[int, Move]] = []
        randomise = level.margin > 0

        for depth in range(1, level.max_depth + 1):
            try:
                scored = self._search_root(pos, moves, depth, full_window=randomise)
            except SearchTimeout:
                break
            last_scored = scored
            best = scored[0][1]
            self._best_prev = best
            if scored[0][0] > MATE - 100:        # forced mate found
                break
        if randomise and last_scored:
            floor = last_scored[0][0] - level.margin
            pool = [m for s, m in last_scored if s >= floor]
            return self.rng.choice(pool)
        return best

    # ----------------------------------------------------------- internals
    def _check_time(self) -> None:
        if (self._stop is not None and self._stop.is_set()) or time.monotonic() > self._deadline:
            raise SearchTimeout

    def _search_root(self, pos: Position, moves: List[Move], depth: int,
                     full_window: bool) -> List[Tuple[int, Move]]:
        ordered = self._order(pos, moves, self._best_prev, 0)
        alpha, beta = -INF, INF
        scored: List[Tuple[int, Move]] = []
        for m in ordered:
            pos.make(m)
            if full_window:
                score = -self._negamax(pos, depth - 1, -INF, INF, 1)
            else:
                score = -self._negamax(pos, depth - 1, -beta, -alpha, 1)
            pos.unmake()
            scored.append((score, m))
            if not full_window and score > alpha:
                alpha = score
        scored.sort(key=lambda t: -t[0])
        return scored

    def _order(self, pos: Position, moves: List[Move], tt_move: Optional[Move], ply: int):
        board = pos.board
        killers = self.killers.get(ply, ())

        def score(m: Move) -> int:
            if tt_move is not None and m == tt_move:
                return 10_000_000
            s = 0
            victim = board[m.to]
            if victim != ".":
                s += 10_000 + 10 * VALUE[victim.upper()] - VALUE[board[m.frm].upper()]
            elif board[m.frm] in "Pp" and (m.frm & 7) != (m.to & 7):
                s += 10_000 + 900                                  # en passant
            if m.promo:
                s += 9_000 + VALUE[m.promo.upper()]
            if s == 0 and m in killers:
                s += 5_000
            return s

        return sorted(moves, key=score, reverse=True)

    def _static(self, pos: Position) -> int:
        value = evaluate(pos)
        return value if pos.turn == WHITE else -value

    def _negamax(self, pos: Position, depth: int, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        if self.nodes & 511 == 0:
            self._check_time()
        if pos.halfmove >= 100 or pos._keys.count(pos._keys[-1]) >= 2:
            return 0                                           # draw by rule / repetition
        key = pos._keys[-1]
        entry = self.tt.get(key)
        tt_move = None
        if entry is not None:
            e_depth, flag, value, tt_move = entry
            if e_depth >= depth:
                if flag == _EXACT:
                    return value
                if flag == _LOWER:
                    alpha = max(alpha, value)
                else:
                    beta = min(beta, value)
                if alpha >= beta:
                    return value
        checked = pos.in_check()
        if checked and ply < 32:
            depth += 1
        if depth <= 0:
            return self._quiesce(pos, alpha, beta, 0)
        moves = pos.legal_moves()
        if not moves:
            return -MATE + ply if checked else 0
        original_alpha = alpha
        best, best_move = -INF, None
        for m in self._order(pos, moves, tt_move, ply):
            pos.make(m)
            score = -self._negamax(pos, depth - 1, -beta, -alpha, ply + 1)
            pos.unmake()
            if score > best:
                best, best_move = score, m
            if best > alpha:
                alpha = best
            if alpha >= beta:
                if pos.board[m.to] == ".":
                    slot = self.killers.setdefault(ply, [])
                    if m not in slot:
                        slot.insert(0, m)
                        del slot[2:]
                break
        flag = _EXACT
        if best <= original_alpha:
            flag = _UPPER
        elif best >= beta:
            flag = _LOWER
        self.tt[key] = (depth, flag, best, best_move)
        return best

    def _quiesce(self, pos: Position, alpha: int, beta: int, qdepth: int) -> int:
        self.nodes += 1
        if self.nodes & 511 == 0:
            self._check_time()
        stand = self._static(pos)
        if stand >= beta or qdepth >= 6:
            return stand
        alpha = max(alpha, stand)
        for m in self._order(pos, pos.legal_moves(captures_only=True), None, 99):
            pos.make(m)
            score = -self._quiesce(pos, -beta, -alpha, qdepth + 1)
            pos.unmake()
            if score >= beta:
                return score
            if score > alpha:
                alpha = score
        return alpha
