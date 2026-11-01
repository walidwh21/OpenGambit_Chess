"""Procedurally drawn chess pieces (no image files, no borrowed artwork).

Each piece is designed on a 100x100 grid, drawn at 4x scale and smoothly
down-scaled, which gives crisp anti-aliased silhouettes at any size.
"""
from __future__ import annotations

from typing import Dict, Tuple

import pygame

Color = Tuple[int, ...]
_SS = 4  # supersampling factor


def _poly(surf, pts, fill, line, width):
    pts = [(x * _SS, y * _SS) for x, y in pts]
    pygame.draw.polygon(surf, fill, pts)
    pygame.draw.polygon(surf, line, pts, width * _SS)
    # round the joints so thick outlines look soft rather than spiky
    for p in pts:
        pygame.draw.circle(surf, line, p, width * _SS // 2)


def _circle(surf, c, r, fill, line, width):
    pygame.draw.circle(surf, fill, (c[0] * _SS, c[1] * _SS), r * _SS)
    pygame.draw.circle(surf, line, (c[0] * _SS, c[1] * _SS), r * _SS, width * _SS)


def _base(surf, fill, line, w):
    _poly(surf, [(24, 87), (76, 87), (73, 77), (27, 77)], fill, line, w)


def _draw(kind: str, surf, fill: Color, line: Color) -> None:
    w = 3
    _base(surf, fill, line, w)
    if kind == "P":
        _poly(surf, [(40, 50), (60, 50), (67, 77), (33, 77)], fill, line, w)
        _poly(surf, [(35, 46), (65, 46), (62, 54), (38, 54)], fill, line, w)
        _circle(surf, (50, 33), 13, fill, line, w)
    elif kind == "R":
        _poly(surf, [(32, 40), (68, 40), (72, 77), (28, 77)], fill, line, w)
        _poly(surf, [(27, 40), (73, 40), (73, 46), (27, 46)], fill, line, w)
        for x0 in (27, 44, 61):
            _poly(surf, [(x0, 20), (x0 + 12, 20), (x0 + 12, 40), (x0, 40)], fill, line, w)
        _poly(surf, [(27, 32), (73, 32), (73, 40), (27, 40)], fill, line, w)
    elif kind == "N":
        _poly(surf, [(26, 77), (31, 56), (42, 45), (33, 41), (27, 46), (21, 41),
                     (33, 25), (45, 17), (47, 8), (55, 16), (67, 23), (76, 42), (74, 77)],
              fill, line, w)
        pygame.draw.circle(surf, line, (52 * _SS, 28 * _SS), 3 * _SS)          # eye
        pygame.draw.circle(surf, line, (30 * _SS, 43 * _SS), 2 * _SS)          # nostril
    elif kind == "B":
        _poly(surf, [(38, 52), (62, 52), (69, 77), (31, 77)], fill, line, w)
        _poly(surf, [(34, 49), (66, 49), (63, 56), (37, 56)], fill, line, w)
        pygame.draw.ellipse(surf, fill, pygame.Rect(37 * _SS, 18 * _SS, 26 * _SS, 33 * _SS))
        pygame.draw.ellipse(surf, line, pygame.Rect(37 * _SS, 18 * _SS, 26 * _SS, 33 * _SS), w * _SS)
        pygame.draw.line(surf, line, (50 * _SS, 26 * _SS), (57 * _SS, 36 * _SS), 3 * _SS)  # mitre slit
        _circle(surf, (50, 14), 5, fill, line, w)
    elif kind == "Q":
        _poly(surf, [(30, 77), (24, 33), (38, 50), (44, 26), (50, 49), (56, 26),
                     (62, 50), (76, 33), (70, 77)], fill, line, w)
        _poly(surf, [(31, 70), (69, 70), (70, 77), (30, 77)], fill, line, w)
        for x, y in ((24, 30), (37, 22), (50, 18), (63, 22), (76, 30)):
            _circle(surf, (x, y), 5, fill, line, w)
    elif kind == "K":
        _poly(surf, [(30, 77), (35, 46), (65, 46), (70, 77)], fill, line, w)
        _poly(surf, [(31, 70), (69, 70), (70, 77), (30, 77)], fill, line, w)
        _poly(surf, [(33, 44), (67, 44), (64, 54), (36, 54)], fill, line, w)
        _poly(surf, [(45, 27), (55, 27), (55, 44), (45, 44)], fill, line, w)
        _poly(surf, [(46, 7), (54, 7), (54, 33), (46, 33)], fill, line, w)
        _poly(surf, [(39, 14), (61, 14), (61, 22), (39, 22)], fill, line, w)


def render_piece(piece: str, size: int, fill: Color, line: Color) -> pygame.Surface:
    """Draw one piece ('K','q',...) onto a transparent size x size surface."""
    big = pygame.Surface((100 * _SS, 100 * _SS), pygame.SRCALPHA)
    _draw(piece.upper(), big, fill[:3], line[:3])
    return pygame.transform.smoothscale(big, (size, size))


class PieceSet:
    """Cache of rendered pieces for one theme."""

    def __init__(self, theme) -> None:
        self.theme = theme
        self._cache: Dict[Tuple[str, int], pygame.Surface] = {}

    def get(self, piece: str, size: int) -> pygame.Surface:
        key = (piece, size)
        if key not in self._cache:
            white = piece.isupper()
            t = self.theme
            fill, line = (t.white_fill, t.white_line) if white else (t.black_fill, t.black_line)
            self._cache[key] = render_piece(piece, size, fill, line)
        return self._cache[key]
