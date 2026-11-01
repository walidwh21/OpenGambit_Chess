"""Chess rules engine.

The board is a flat list of 64 single-character cells (``'.'`` for empty).
Upper-case letters are White pieces, lower-case letters are Black pieces,
exactly like the piece-placement field of a FEN string.  Square ``0`` is a8
and square ``63`` is h1, so ``row = sq >> 3`` and ``col = sq & 7``.

The engine is UI-free and has no third-party dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

FILES = "abcdefgh"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
WHITE, BLACK = "w", "b"


def other(color: str) -> str:
    return BLACK if color == WHITE else WHITE


def sq_name(sq: int) -> str:
    return FILES[sq & 7] + str(8 - (sq >> 3))


def name_sq(name: str) -> int:
    return (8 - int(name[1])) * 8 + FILES.index(name[0])


# --------------------------------------------------------------------------
# Pre-computed geometry
# --------------------------------------------------------------------------
def _build_geometry():
    knight, king, ortho, diag = [], [], [], []

    def inside(rr, cc):
        return 0 <= rr < 8 and 0 <= cc < 8

    for sq in range(64):
        r, c = divmod(sq, 8)
        knight.append([
            (r + dr) * 8 + c + dc
            for dr, dc in ((-2, -1), (-2, 1), (-1, -2), (-1, 2),
                           (1, -2), (1, 2), (2, -1), (2, 1))
            if inside(r + dr, c + dc)
        ])
        king.append([
            (r + dr) * 8 + c + dc
            for dr in (-1, 0, 1) for dc in (-1, 0, 1)
            if (dr or dc) and inside(r + dr, c + dc)
        ])

        def rays(directions):
            out = []
            for dr, dc in directions:
                ray, rr, cc = [], r + dr, c + dc
                while inside(rr, cc):
                    ray.append(rr * 8 + cc)
                    rr += dr
                    cc += dc
                if ray:
                    out.append(ray)
            return out

        ortho.append(rays(((-1, 0), (1, 0), (0, -1), (0, 1))))
        diag.append(rays(((-1, -1), (-1, 1), (1, -1), (1, 1))))
    return knight, king, ortho, diag


KNIGHT_TARGETS, KING_TARGETS, ORTHO_RAYS, DIAG_RAYS = _build_geometry()

# Which castling rights disappear when a piece moves from / to a square.
_RIGHTS_LOST = {0: "q", 4: "kq", 7: "k", 56: "Q", 60: "KQ", 63: "K"}


class Move:
    """A move: origin, destination and (optional) promotion piece letter."""

    __slots__ = ("frm", "to", "promo")

    def __init__(self, frm: int, to: int, promo: Optional[str] = None):
        self.frm = frm
        self.to = to
        self.promo = promo

    def uci(self) -> str:
        return sq_name(self.frm) + sq_name(self.to) + (self.promo or "")

    def __eq__(self, other_move) -> bool:
        return (isinstance(other_move, Move) and self.frm == other_move.frm
                and self.to == other_move.to and self.promo == other_move.promo)

    def __hash__(self) -> int:
        return hash((self.frm, self.to, self.promo))

    def __repr__(self) -> str:
        return f"Move({self.uci()})"


@dataclass(frozen=True)
class Outcome:
    """Why and how a game ended."""
    kind: str                      # checkmate | stalemate | fifty | repetition | material
    winner: Optional[str] = None   # 'w', 'b' or None for draws

    def describe(self) -> str:
        if self.kind == "checkmate":
            side = "White" if self.winner == WHITE else "Black"
            return f"Checkmate \u2014 {side} wins"
        return {
            "stalemate": "Draw by stalemate",
            "fifty": "Draw by the fifty-move rule",
            "repetition": "Draw by threefold repetition",
            "material": "Draw \u2014 insufficient material",
        }[self.kind]


class Position:
    """Full game state plus make / unmake and legal move generation."""

    def __init__(self, fen: str = START_FEN):
        self.set_fen(fen)

    # ----------------------------------------------------------- set-up
    def set_fen(self, fen: str) -> None:
        parts = fen.split()
        board: List[str] = []
        for ch in parts[0]:
            if ch == "/":
                continue
            if ch.isdigit():
                board.extend("." * int(ch))
            else:
                board.append(ch)
        if len(board) != 64:
            raise ValueError(f"Bad FEN board field: {parts[0]!r}")
        self.board = board
        self.turn = parts[1] if len(parts) > 1 else WHITE
        castling = parts[2] if len(parts) > 2 else "-"
        self.castling = "" if castling == "-" else castling
        ep = parts[3] if len(parts) > 3 else "-"
        self.ep = -1 if ep == "-" else name_sq(ep)
        self.halfmove = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 else 1
        self.king_sq = {WHITE: board.index("K"), BLACK: board.index("k")}
        self._undo: list = []
        self._keys: List[str] = [self.key()]

    def fen(self) -> str:
        rows = []
        for r in range(8):
            row, empty = "", 0
            for ch in self.board[r * 8:(r + 1) * 8]:
                if ch == ".":
                    empty += 1
                else:
                    row += (str(empty) if empty else "") + ch
                    empty = 0
            rows.append(row + (str(empty) if empty else ""))
        ep = "-" if self.ep < 0 else sq_name(self.ep)
        return (f"{'/'.join(rows)} {self.turn} {self.castling or '-'} {ep} "
                f"{self.halfmove} {self.fullmove}")

    def copy(self) -> "Position":
        clone = Position.__new__(Position)
        clone.board = self.board[:]
        clone.turn = self.turn
        clone.castling = self.castling
        clone.ep = self.ep
        clone.halfmove = self.halfmove
        clone.fullmove = self.fullmove
        clone.king_sq = dict(self.king_sq)
        clone._undo = []
        clone._keys = self._keys[:]
        return clone

    def key(self) -> str:
        """Hashable identity of the position (for repetition and tables)."""
        ep = ""
        if self.ep >= 0:  # en-passant only matters if a capture is possible
            pawn = "P" if self.turn == WHITE else "p"
            r, c = divmod(self.ep, 8)
            pr = r + 1 if self.turn == WHITE else r - 1
            for dc in (-1, 1):
                if 0 <= c + dc < 8 and self.board[pr * 8 + c + dc] == pawn:
                    ep = str(self.ep)
        return "".join(self.board) + self.turn + self.castling + ep

    # ------------------------------------------------------ attack tests
    def is_attacked(self, sq: int, by: str) -> bool:
        b = self.board
        white = by == WHITE
        r, c = sq >> 3, sq & 7
        pr = r + 1 if white else r - 1
        if 0 <= pr < 8:
            pawn = "P" if white else "p"
            if c > 0 and b[pr * 8 + c - 1] == pawn:
                return True
            if c < 7 and b[pr * 8 + c + 1] == pawn:
                return True
        knight, king = ("N", "K") if white else ("n", "k")
        for t in KNIGHT_TARGETS[sq]:
            if b[t] == knight:
                return True
        for t in KING_TARGETS[sq]:
            if b[t] == king:
                return True
        rook, bishop, queen = ("R", "B", "Q") if white else ("r", "b", "q")
        for ray in ORTHO_RAYS[sq]:
            for t in ray:
                p = b[t]
                if p != ".":
                    if p == rook or p == queen:
                        return True
                    break
        for ray in DIAG_RAYS[sq]:
            for t in ray:
                p = b[t]
                if p != ".":
                    if p == bishop or p == queen:
                        return True
                    break
        return False

    def in_check(self, color: Optional[str] = None) -> bool:
        color = color or self.turn
        return self.is_attacked(self.king_sq[color], other(color))

    # ---------------------------------------------------- move generation
    def pseudo_moves(self, captures_only: bool = False) -> List[Move]:
        b = self.board
        white = self.turn == WHITE
        out: List[Move] = []
        add = out.append
        for sq in range(64):
            p = b[sq]
            if p == "." or p.isupper() != white:
                continue
            kind = p.upper()
            if kind == "P":
                step = -8 if white else 8
                promo_row = 0 if white else 7
                fwd = sq + step
                if b[fwd] == ".":
                    if fwd >> 3 == promo_row:
                        for pr in "qrbn":
                            add(Move(sq, fwd, pr))
                    elif not captures_only:
                        add(Move(sq, fwd))
                        start_row = 6 if white else 1
                        if sq >> 3 == start_row and b[fwd + step] == ".":
                            add(Move(sq, fwd + step))
                col = sq & 7
                for dc in (-1, 1):
                    if not 0 <= col + dc < 8:
                        continue
                    t = fwd + dc
                    target = b[t]
                    if target != "." and target.isupper() != white:
                        if t >> 3 == promo_row:
                            for pr in "qrbn":
                                add(Move(sq, t, pr))
                        else:
                            add(Move(sq, t))
                    elif t == self.ep:
                        add(Move(sq, t))
            elif kind in "NK":
                table = KNIGHT_TARGETS if kind == "N" else KING_TARGETS
                for t in table[sq]:
                    target = b[t]
                    if target == ".":
                        if not captures_only:
                            add(Move(sq, t))
                    elif target.isupper() != white:
                        add(Move(sq, t))
                if kind == "K" and not captures_only:
                    self._castling_moves(sq, out)
            else:
                rays = []
                if kind in "RQ":
                    rays += ORTHO_RAYS[sq]
                if kind in "BQ":
                    rays += DIAG_RAYS[sq]
                for ray in rays:
                    for t in ray:
                        target = b[t]
                        if target == ".":
                            if not captures_only:
                                add(Move(sq, t))
                            continue
                        if target.isupper() != white:
                            add(Move(sq, t))
                        break
        return out

    def _castling_moves(self, sq: int, out: List[Move]) -> None:
        b = self.board
        white = self.turn == WHITE
        home = 60 if white else 4
        if sq != home or not self.castling:
            return
        foe = other(self.turn)
        rook = "R" if white else "r"
        k_right, q_right = ("K", "Q") if white else ("k", "q")
        if self.is_attacked(home, foe):
            return
        if (k_right in self.castling and b[home + 1] == "." and b[home + 2] == "."
                and b[home + 3] == rook
                and not self.is_attacked(home + 1, foe)
                and not self.is_attacked(home + 2, foe)):
            out.append(Move(home, home + 2))
        if (q_right in self.castling and b[home - 1] == "." and b[home - 2] == "."
                and b[home - 3] == "." and b[home - 4] == rook
                and not self.is_attacked(home - 1, foe)
                and not self.is_attacked(home - 2, foe)):
            out.append(Move(home, home - 2))

    def legal_moves(self, captures_only: bool = False) -> List[Move]:
        us, them = self.turn, other(self.turn)
        legal = []
        for m in self.pseudo_moves(captures_only):
            self.make(m)
            if not self.is_attacked(self.king_sq[us], them):
                legal.append(m)
            self.unmake()
        return legal

    # ---------------------------------------------------------- make/unmake
    def make(self, m: Move) -> str:
        """Play ``m`` (assumed legal). Returns the captured piece or '.'."""
        b = self.board
        frm, to = m.frm, m.to
        piece = b[frm]
        white = piece.isupper()
        kind = piece.upper()
        captured, cap_sq = b[to], to
        if kind == "P" and to == self.ep and captured == "." and (frm & 7) != (to & 7):
            cap_sq = to + 8 if white else to - 8
            captured = b[cap_sq]
            b[cap_sq] = "."
        self._undo.append((m, piece, captured, cap_sq, self.castling, self.ep, self.halfmove))

        b[frm] = "."
        b[to] = (m.promo.upper() if white else m.promo.lower()) if m.promo else piece
        if kind == "K":
            self.king_sq[self.turn] = to
            if abs(to - frm) == 2:  # castling: relocate the rook
                if to > frm:
                    b[to - 1], b[to + 1] = b[to + 1], "."
                else:
                    b[to + 1], b[to - 2] = b[to - 2], "."
        if self.castling:
            lost = _RIGHTS_LOST.get(frm, "") + _RIGHTS_LOST.get(to, "")
            if lost:
                self.castling = "".join(ch for ch in self.castling if ch not in lost)
        self.ep = (frm + to) // 2 if kind == "P" and abs(to - frm) == 16 else -1
        self.halfmove = 0 if kind == "P" or captured != "." else self.halfmove + 1
        if self.turn == BLACK:
            self.fullmove += 1
        self.turn = other(self.turn)
        self._keys.append(self.key())
        return captured

    def unmake(self) -> None:
        m, piece, captured, cap_sq, castling, ep, halfmove = self._undo.pop()
        self._keys.pop()
        self.turn = other(self.turn)
        if self.turn == BLACK:
            self.fullmove -= 1
        b = self.board
        b[m.to] = "."
        b[m.frm] = piece
        if captured != ".":
            b[cap_sq] = captured
        if piece.upper() == "K":
            self.king_sq[self.turn] = m.frm
            if abs(m.to - m.frm) == 2:
                if m.to > m.frm:
                    b[m.to + 1], b[m.to - 1] = b[m.to - 1], "."
                else:
                    b[m.to - 2], b[m.to + 1] = b[m.to + 1], "."
        self.castling, self.ep, self.halfmove = castling, ep, halfmove

    # ---------------------------------------------------------- notation
    def san(self, m: Move) -> str:
        """Standard algebraic notation for a legal move in this position."""
        b = self.board
        piece = b[m.frm]
        kind = piece.upper()
        if kind == "K" and abs(m.to - m.frm) == 2:
            text = "O-O" if m.to > m.frm else "O-O-O"
        else:
            capture = b[m.to] != "." or (kind == "P" and (m.frm & 7) != (m.to & 7))
            if kind == "P":
                text = (FILES[m.frm & 7] + "x" if capture else "") + sq_name(m.to)
                if m.promo:
                    text += "=" + m.promo.upper()
            else:
                text = kind
                rivals = [o for o in self.legal_moves()
                          if o.to == m.to and o.frm != m.frm and b[o.frm] == piece]
                if rivals:
                    if not any((o.frm & 7) == (m.frm & 7) for o in rivals):
                        text += FILES[m.frm & 7]
                    elif not any((o.frm >> 3) == (m.frm >> 3) for o in rivals):
                        text += str(8 - (m.frm >> 3))
                    else:
                        text += sq_name(m.frm)
                text += ("x" if capture else "") + sq_name(m.to)
        self.make(m)
        if self.in_check():
            text += "#" if not self.legal_moves() else "+"
        self.unmake()
        return text

    def parse_san(self, token: str) -> Move:
        wanted = token.strip().replace("0", "O").rstrip("+#!?")
        for m in self.legal_moves():
            if self.san(m).rstrip("+#") == wanted:
                return m
        raise ValueError(f"Illegal or unknown move {token!r} in {self.fen()}")

    def parse_uci(self, text: str) -> Move:
        for m in self.legal_moves():
            if m.uci() == text.strip():
                return m
        raise ValueError(f"Illegal move {text!r} in {self.fen()}")

    # --------------------------------------------------------- game status
    def insufficient_material(self) -> bool:
        pieces = [(i, p) for i, p in enumerate(self.board)
                  if p != "." and p.upper() != "K"]
        if not pieces:
            return True
        if len(pieces) == 1:
            return pieces[0][1].upper() in "NB"
        if all(p.upper() == "B" for _, p in pieces):
            shades = {((i >> 3) + (i & 7)) & 1 for i, _ in pieces}
            return len(shades) == 1
        return False

    def outcome(self) -> Optional[Outcome]:
        if not self.legal_moves():
            if self.in_check():
                return Outcome("checkmate", other(self.turn))
            return Outcome("stalemate")
        if self.halfmove >= 100:
            return Outcome("fifty")
        if self._keys.count(self._keys[-1]) >= 3:
            return Outcome("repetition")
        if self.insufficient_material():
            return Outcome("material")
        return None

    def perft(self, depth: int) -> int:
        """Count leaf nodes of the legal-move tree (used by the test-suite)."""
        if depth == 0:
            return 1
        total = 0
        for m in self.legal_moves():
            self.make(m)
            total += self.perft(depth - 1)
            self.unmake()
        return total
