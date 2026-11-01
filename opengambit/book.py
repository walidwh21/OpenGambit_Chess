"""Opening book loaded from plain JSON (no pickle, safe to edit by hand)."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .engine import Move, Position

DEFAULT_PATH = Path(__file__).with_name("data") / "openings.json"


class OpeningBook:
    def __init__(self) -> None:
        self._moves: Dict[str, List[Move]] = {}
        self._names: Dict[str, Tuple[int, str]] = {}

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "OpeningBook":
        book = cls()
        data = json.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
        for line in data["lines"]:
            book.add_line(line["name"], line["moves"].split(), line.get("named_from", 1))
        return book

    def add_line(self, name: str, san_moves: List[str], named_from: int = 1) -> None:
        pos = Position()
        for ply, token in enumerate(san_moves, start=1):
            move = pos.parse_san(token)            # raises ValueError on typos
            bucket = self._moves.setdefault(pos.key(), [])
            if move not in bucket:
                bucket.append(move)
            pos.make(move)
            if ply >= named_from:
                known = self._names.get(pos.key())
                if known is None or ply > known[0]:
                    self._names[pos.key()] = (ply, name)

    def pick(self, pos: Position, rng: Optional[random.Random] = None) -> Optional[Move]:
        options = self._moves.get(pos.key())
        if not options:
            return None
        return (rng or random).choice(options)

    def name_for(self, pos: Position) -> Optional[str]:
        hit = self._names.get(pos.key())
        return hit[1] if hit else None

    def __len__(self) -> int:
        return len(self._moves)
