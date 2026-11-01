"""Game session: wraps a Position with history, captures, undo and status text.

Has no pygame dependency, so it can be unit-tested and reused by other front-ends.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .ai import LEVELS, VALUE, Level
from .book import OpeningBook
from .engine import BLACK, WHITE, Move, Outcome, Position, other


@dataclass
class Entry:
    move: Move
    san: str
    captured: str          # captured piece letter or '.'
    opening: Optional[str] = None   # most recent named opening reached so far


class Game:
    def __init__(self, vs_computer: bool = True, human_color: str = WHITE,
                 level: Optional[Level] = None, book: Optional[OpeningBook] = None) -> None:
        self.pos = Position()
        self.vs_computer = vs_computer
        self.human_color = human_color
        self.level = level or LEVELS["casual"]
        self.book = book
        self.entries: List[Entry] = []
        self.outcome: Optional[Outcome] = None

    # ------------------------------------------------------------ queries
    @property
    def turn(self) -> str:
        return self.pos.turn

    @property
    def computer_color(self) -> Optional[str]:
        return other(self.human_color) if self.vs_computer else None

    def is_computer_turn(self) -> bool:
        return self.outcome is None and self.vs_computer and self.turn == self.computer_color

    def legal_from(self, sq: int) -> List[Move]:
        if self.outcome is not None:
            return []
        return [m for m in self.pos.legal_moves() if m.frm == sq]

    @property
    def last_move(self) -> Optional[Move]:
        return self.entries[-1].move if self.entries else None

    def captured_by(self, color: str) -> List[str]:
        """Pieces (of the opposite colour) that ``color`` has captured."""
        want_upper = color == BLACK
        got = [e.captured for e in self.entries
               if e.captured != "." and e.captured.isupper() == want_upper]
        return sorted(got, key=lambda p: -VALUE[p.upper()])

    def material_balance(self) -> int:
        """Positive when White is ahead (in pawns)."""
        total = 0
        for e in self.entries:
            if e.captured != ".":
                v = VALUE[e.captured.upper()]
                total += v if e.captured.islower() else -v
        return total // 100

    def move_pairs(self) -> List[tuple]:
        """[(move_number, white_san, black_san_or_None), ...]"""
        pairs = []
        sans = [e.san for e in self.entries]
        for i in range(0, len(sans), 2):
            pairs.append((i // 2 + 1, sans[i], sans[i + 1] if i + 1 < len(sans) else None))
        return pairs

    def opening_name(self) -> Optional[str]:
        return self.entries[-1].opening if self.entries else None

    def status(self) -> str:
        if self.outcome is not None:
            return self.outcome.describe()
        side = "White" if self.turn == WHITE else "Black"
        if self.pos.in_check():
            return f"{side} is in check"
        return f"{side} to move"

    # ----------------------------------------------------------- mutation
    def play(self, move: Move) -> str:
        san = self.pos.san(move)
        captured = self.pos.make(move)
        opening = self.book.name_for(self.pos) if self.book else None
        if opening is None and self.entries:
            opening = self.entries[-1].opening
        self.entries.append(Entry(move, san, captured, opening))
        self.outcome = self.pos.outcome()
        return san

    def undo(self, plies: int = 1) -> int:
        done = 0
        for _ in range(plies):
            if not self.entries:
                break
            self.entries.pop()
            self.pos.unmake()
            done += 1
        self.outcome = self.pos.outcome() if done else self.outcome
        return done

    def undo_to_human(self) -> int:
        """Take back moves until it is the human's turn again (vs computer)."""
        if not self.vs_computer:
            return self.undo(1)
        done = self.undo(1)
        if self.turn != self.human_color:
            done += self.undo(1)
        return done
