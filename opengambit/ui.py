"""pygame front-end: menu, themed board, drag & drop / click-to-move, side panel."""
from __future__ import annotations

import random
import threading
import time
from typing import Callable, List, Optional, Tuple

import pygame

from .ai import LEVELS, Searcher
from .book import OpeningBook
from .engine import BLACK, WHITE, Move, sq_name, name_sq
from .game import Game
from .pieces import PieceSet
from .themes import Theme, load_themes

# ----------------------------------------------------------------- layout
WIN_W, WIN_H = 1000, 680
SQ = 80
BOARD_X, BOARD_Y = 20, 20
BOARD_RECT = pygame.Rect(BOARD_X, BOARD_Y, SQ * 8, SQ * 8)
SIDE_X, SIDE_W = 680, 300
FONT_STACK = "segoeui,helveticaneue,helvetica,arial,dejavusans,liberationsans"
APP_NAME = "OpenGambit"


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


class App:
    def __init__(self, theme_id: Optional[str] = None) -> None:
        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption(APP_NAME)

        self.themes: List[Theme] = load_themes()
        self.theme: Theme = self.themes[0]
        self.piece_set = PieceSet(self.theme)
        self.set_theme(theme_id or self.themes[0].id)
        self.book = OpeningBook.load()
        self._fonts = {}
        self._glow_cache = {}
        self._tint_cache = {}

        self.mode = "menu"                      # "menu" | "game"
        self.menu = {"mode": "ai", "color": "w", "level": "casual", "autoflip": True}
        self.game: Optional[Game] = None
        self.flipped = False
        self.autoflip = False
        self.selected: Optional[int] = None
        self.targets: List[Move] = []
        self.drag: Optional[dict] = None
        self.anim: Optional[dict] = None
        self.promo: Optional[dict] = None
        self.hits: List[Tuple[pygame.Rect, Callable]] = []
        self.move_scroll = 0
        self.banner_dismissed = False
        self.running = True

        self._ai_token = 0
        self._ai_stop = threading.Event()
        self._ai_result: Optional[tuple] = None
        self._ai_started = 0.0
        self.min_think_seconds = 0.5

    # ------------------------------------------------------------- themes
    def set_theme(self, theme_id: str) -> None:
        for t in self.themes:
            if t.id == theme_id:
                self.theme = t
                self.piece_set = PieceSet(t)
                self._glow_cache = {}
                self._tint_cache = {}
                return
        raise KeyError(f"Unknown theme {theme_id!r}")

    def cycle_theme(self) -> None:
        ids = [t.id for t in self.themes]
        self.set_theme(ids[(ids.index(self.theme.id) + 1) % len(ids)])

    # --------------------------------------------------------- game control
    def start_game(self, vs_computer: bool = True, human_color: str = WHITE,
                   level: str = "casual", autoflip: bool = True) -> None:
        self.cancel_ai()
        if human_color == "r":
            human_color = random.choice([WHITE, BLACK])
        self.game = Game(vs_computer, human_color, LEVELS[level], self.book)
        self.autoflip = autoflip and not vs_computer
        self.flipped = vs_computer and human_color == BLACK
        self.selected, self.targets, self.drag = None, [], None
        self.anim, self.promo, self.move_scroll = None, None, 0
        self.banner_dismissed = False
        self.mode = "game"
        if self.game.is_computer_turn():
            self._start_ai()

    def restart(self) -> None:
        g = self.game
        if g is None:
            return
        self.start_game(g.vs_computer, g.human_color, g.level.key, self.autoflip)

    def play_san(self, *tokens: str) -> None:
        """Play moves programmatically (used by tests and the screenshot tool)."""
        for token in tokens:
            move = self.game.pos.parse_san(token)
            self.game.play(move)
        self.after_move()

    def select_square(self, name: str) -> None:
        sq = name_sq(name)
        self.selected = sq
        self.targets = self.game.legal_from(sq)

    def can_move_now(self) -> bool:
        g = self.game
        return (self.mode == "game" and g is not None and g.outcome is None
                and self.anim is None and self.promo is None and not g.is_computer_turn())

    def commit(self, move: Move, animate: bool) -> None:
        piece = self.game.pos.board[move.frm]
        self.game.play(move)
        self.selected, self.targets, self.drag = None, [], None
        if animate:
            self.anim = {"piece": piece, "frm": move.frm, "to": move.to,
                         "t0": time.monotonic(), "dur": 0.22}
        self.after_move()

    def after_move(self) -> None:
        self.move_scroll = 0
        self.banner_dismissed = False
        if self.autoflip and self.game.outcome is None:
            self.flipped = self.game.turn == BLACK
        if self.game.is_computer_turn():
            self._start_ai()

    def try_move(self, frm: int, to: int, animate: bool) -> None:
        candidates = [m for m in self.targets if m.frm == frm and m.to == to]
        if not candidates:
            return
        if len(candidates) > 1:                       # promotion: ask which piece
            self.promo = {"moves": candidates, "color": self.game.turn}
            return
        self.commit(candidates[0], animate)

    def do_undo(self) -> None:
        if self.game is None or not self.game.entries:
            return
        self.cancel_ai()
        self.game.undo_to_human()
        self.anim, self.promo = None, None
        self.banner_dismissed = False
        self.selected, self.targets, self.drag = None, [], None
        if self.autoflip:
            self.flipped = self.game.turn == BLACK
        if self.game.is_computer_turn():
            self._start_ai()

    # ------------------------------------------------------------------ AI
    def cancel_ai(self) -> None:
        self._ai_stop.set()
        self._ai_token += 1
        self._ai_result = None

    def _start_ai(self) -> None:
        self._ai_token += 1
        token = self._ai_token
        self._ai_stop = threading.Event()
        stop = self._ai_stop
        pos = self.game.pos.copy()
        level = self.game.level
        searcher = Searcher(self.book)
        self._ai_started = time.monotonic()
        self._ai_result = None

        def work() -> None:
            move = searcher.choose(pos, level, stop)
            if not stop.is_set():
                self._ai_result = (token, move)

        threading.Thread(target=work, daemon=True).start()

    def is_thinking(self) -> bool:
        return self.game is not None and self.game.is_computer_turn()

    # --------------------------------------------------------------- events
    def handle_event(self, e: pygame.event.Event) -> None:
        if e.type == pygame.QUIT:
            self.running = False
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self._mouse_down(e.pos)
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self._mouse_up(e.pos)
        elif e.type == pygame.MOUSEMOTION and self.drag:
            self.drag["pos"] = e.pos
        elif e.type == pygame.MOUSEWHEEL and self.mode == "game":
            self.move_scroll = max(0, self.move_scroll - e.y)
        elif e.type == pygame.KEYDOWN:
            self._key(e.key)

    def _key(self, key: int) -> None:
        if key == pygame.K_ESCAPE:
            if self.promo:
                self.promo = None
            elif self.game is not None and self.mode == "game" and self.game.outcome and not self.banner_dismissed:
                self.banner_dismissed = True
            elif self.selected is not None:
                self.selected, self.targets = None, []
            elif self.mode == "game":
                self.mode = "menu"
        elif key == pygame.K_t:
            self.cycle_theme()
        elif self.mode == "game":
            if key == pygame.K_n:
                self.restart()
            elif key == pygame.K_u:
                self.do_undo()
            elif key == pygame.K_f:
                self.flipped = not self.flipped
            elif key == pygame.K_m:
                self.mode = "menu"
        elif self.mode == "menu" and key in (pygame.K_RETURN, pygame.K_SPACE):
            self._start_from_menu()

    def _mouse_down(self, pos) -> None:
        if self.promo:
            self._promo_click(pos)
            return
        for rect, action in reversed(self.hits):
            if rect.collidepoint(pos):
                action()
                return
        if (self.mode == "game" and self.game.outcome is not None and not self.banner_dismissed
                and BOARD_RECT.collidepoint(pos)):
            self.banner_dismissed = True
            return
        if self.mode != "game" or not self.can_move_now():
            return
        sq = self.px_to_sq(pos)
        if sq is None:
            self.selected, self.targets = None, []
            return
        if self.selected is not None and any(m.to == sq for m in self.targets):
            self.try_move(self.selected, sq, animate=True)
            return
        piece = self.game.pos.board[sq]
        mine = piece != "." and piece.isupper() == (self.game.turn == WHITE)
        if mine:
            toggle = sq == self.selected
            self.selected = sq
            self.targets = self.game.legal_from(sq)
            self.drag = {"sq": sq, "pos": pos, "toggle": toggle}
        else:
            self.selected, self.targets = None, []

    def _mouse_up(self, pos) -> None:
        if not self.drag:
            return
        drag, self.drag = self.drag, None
        sq = self.px_to_sq(pos)
        if sq is None:
            return
        if sq == drag["sq"]:
            if drag["toggle"]:
                self.selected, self.targets = None, []
            return
        if any(m.to == sq for m in self.targets):
            self.try_move(drag["sq"], sq, animate=False)
        else:
            self.selected, self.targets = None, []

    def _promo_click(self, pos) -> None:
        for rect, move in self._promo_slots():
            if rect.collidepoint(pos):
                self.promo = None
                self.commit(move, animate=False)
                return
        self.promo = None

    # ------------------------------------------------------------ geometry
    def sq_rect(self, sq: int) -> pygame.Rect:
        r, c = divmod(sq, 8)
        if self.flipped:
            r, c = 7 - r, 7 - c
        return pygame.Rect(BOARD_X + c * SQ, BOARD_Y + r * SQ, SQ, SQ)

    def px_to_sq(self, pos) -> Optional[int]:
        if not BOARD_RECT.collidepoint(pos):
            return None
        c, r = (pos[0] - BOARD_X) // SQ, (pos[1] - BOARD_Y) // SQ
        if self.flipped:
            r, c = 7 - r, 7 - c
        return r * 8 + c

    # --------------------------------------------------------------- update
    def update(self) -> None:
        if self.anim and time.monotonic() - self.anim["t0"] >= self.anim["dur"]:
            self.anim = None
        if (self._ai_result and self._ai_result[0] == self._ai_token and self.anim is None
                and self.promo is None and self.game is not None
                and time.monotonic() - self._ai_started >= self.min_think_seconds):
            _, move = self._ai_result
            self._ai_result = None
            if move is not None and self.game.is_computer_turn():
                self.commit(move, animate=True)

    # -------------------------------------------------------------- drawing
    def font(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (size, bold)
        if key not in self._fonts:
            self._fonts[key] = pygame.font.SysFont(FONT_STACK, size, bold=bold)
        return self._fonts[key]

    def text(self, s: str, pos, size=16, color=None, bold=False, anchor="topleft") -> pygame.Rect:
        color = color or self.theme.text
        img = self.font(size, bold).render(s, True, color[:3])
        rect = img.get_rect(**{anchor: pos})
        self.screen.blit(img, rect)
        return rect

    def rrect(self, rect, color, radius=10, border=0, border_color=None) -> None:
        rect = pygame.Rect(rect)
        if len(color) == 4 and color[3] < 255:
            layer = pygame.Surface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(layer, color, layer.get_rect(), border_radius=radius)
            self.screen.blit(layer, rect.topleft)
        else:
            pygame.draw.rect(self.screen, color[:3], rect, border_radius=radius)
        if border:
            pygame.draw.rect(self.screen, (border_color or color)[:3], rect, border, border_radius=radius)

    def tint(self, color) -> pygame.Surface:
        if color not in self._tint_cache:
            s = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
            s.fill(color if len(color) == 4 else (*color, 255))
            self._tint_cache[color] = s
        return self._tint_cache[color]

    def glow(self, color) -> pygame.Surface:
        if color not in self._glow_cache:
            s = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
            for r in range(SQ // 2, 0, -1):
                a = int(245 * (1 - r / (SQ / 2)) ** 0.9)
                pygame.draw.circle(s, (*color[:3], a), (SQ // 2, SQ // 2), r)
            self._glow_cache[color] = s
        return self._glow_cache[color]

    def button(self, rect, label, action, *, enabled=True, selected=False, size=16,
               primary=False, sub=None) -> None:
        t = self.theme
        rect = pygame.Rect(rect)
        hover = enabled and rect.collidepoint(pygame.mouse.get_pos())
        if primary:
            fill = _mix(t.accent, (255, 255, 255), 0.12 if hover else 0)
            fg = t.accent_text
        else:
            fill = _mix(t.panel_alt, t.accent, 0.18 if hover else (0.10 if selected else 0))
            fg = t.text if enabled else _mix(t.muted, t.panel_alt, 0.5)
        self.rrect(rect, fill, 10, 2 if selected else 0, t.accent)
        if sub:
            self.text(label, (rect.centerx, rect.centery - 8), size, fg, True, "center")
            self.text(sub, (rect.centerx, rect.centery + 11), 12, t.muted if not primary else fg, False, "center")
        else:
            self.text(label, rect.center, size, fg, primary or selected, "center")
        if enabled:
            self.hits.append((rect, action))

    def draw(self) -> None:
        self.hits = []
        self.screen.fill(self.theme.bg[:3])
        if self.mode == "menu":
            self._draw_menu()
        else:
            self._draw_board()
            self._draw_sidebar()
            if self.promo:
                self._draw_promotion()
            elif self.game.outcome is not None and self.anim is None and not self.banner_dismissed:
                self._draw_end_banner()

    # ---------------------------------------------------------------- menu
    def _start_from_menu(self) -> None:
        m = self.menu
        self.start_game(m["mode"] == "ai", m["color"], m["level"], m["autoflip"])

    def _chip_row(self, y, items, selected, setter, enabled=True) -> None:
        n = len(items)
        gap = 16
        w = (660 - gap * (n - 1)) // n
        for i, (value, label) in enumerate(items):
            rect = (170 + i * (w + gap), y, w, 44)
            self.button(rect, label, lambda v=value: setter(v), enabled=enabled,
                        selected=(selected == value and enabled), size=16)

    def _draw_menu(self) -> None:
        t, m = self.theme, self.menu
        card = pygame.Rect(130, 30, 740, 612)
        self.rrect(card, t.panel, 20)
        self.text(APP_NAME, (card.centerx, 74), 46, t.text, True, "center")
        self.text(t.tagline, (card.centerx, 112), 18, t.accent, False, "center")

        ai = m["mode"] == "ai"
        self.text("MODE", (170, 146), 13, t.muted, True)
        self._chip_row(166, [("ai", "Vs Computer"), ("two", "Two Players")], m["mode"],
                       lambda v: m.update(mode=v))
        self.text("PLAY AS", (170, 228), 13, t.muted, True)
        self._chip_row(248, [("w", "White"), ("b", "Black"), ("r", "Random")], m["color"],
                       lambda v: m.update(color=v), enabled=ai)
        if ai:
            self.text("DIFFICULTY", (170, 310), 13, t.muted, True)
            self._chip_row(330, [(k, lv.name) for k, lv in LEVELS.items()], m["level"],
                           lambda v: m.update(level=v))
        else:
            self.text("BOARD", (170, 310), 13, t.muted, True)
            self._chip_row(330, [(False, "Fixed view"), (True, "Turn after each move")],
                           m["autoflip"], lambda v: m.update(autoflip=v))

        self.text("THEME", (170, 392), 13, t.muted, True)
        for i, th in enumerate(self.themes):
            col, row = i % 3, i // 3
            rect = pygame.Rect(170 + col * (209 + 16), 412 + row * (62 + 10), 209, 62)
            chosen = th.id == t.id
            hover = rect.collidepoint(pygame.mouse.get_pos())
            self.rrect(rect, _mix(t.panel_alt, t.accent, 0.12 if hover else 0), 10,
                       2 if chosen else 0, t.accent)
            for k, c in enumerate((th.light_sq, th.dark_sq, th.accent)):      # colour swatch
                pygame.draw.rect(self.screen, c[:3], (rect.x + 12 + k * 12, rect.y + 14, 12, 34),
                                 border_radius=3 if k in (0, 2) else 0)
            self.text(th.name, (rect.x + 58, rect.y + 11), 17, t.text, True)
            self.text(th.subtitle, (rect.x + 58, rect.y + 35), 12, t.muted)
            self.hits.append((rect, lambda tid=th.id: self.set_theme(tid)))

        self.button((170, 574, 660, 50), "Start game", self._start_from_menu, primary=True, size=20)
        self.text("Brand-inspired themes are unofficial colour palettes: no logos, no affiliation.",
                  (WIN_W // 2, 660), 12, t.muted, anchor="center")

    # --------------------------------------------------------------- board
    def _draw_board(self) -> None:
        t, g = self.theme, self.game
        for sq in range(64):
            r, c = divmod(sq, 8)
            light = (r + c) % 2 == 0
            rect = self.sq_rect(sq)
            pygame.draw.rect(self.screen, (t.light_sq if light else t.dark_sq)[:3], rect)
            vis_r, vis_c = (7 - r, 7 - c) if self.flipped else (r, c)
            square = (t.light_sq if light else t.dark_sq)
            lum = (square[0] * 299 + square[1] * 587 + square[2] * 114) / 1000
            label_color = _mix(square, (0, 0, 0) if lum > 140 else (255, 255, 255), 0.62)
            if vis_c == 0:
                self.text(str(8 - r), (rect.x + 5, rect.y + 3), 13, label_color, True)
            if vis_r == 7:
                self.text("abcdefgh"[c], (rect.right - 5, rect.bottom - 3), 13, label_color, True, "bottomright")

        last = g.last_move
        if last is not None and self.anim is None:
            for sq in (last.frm, last.to):
                self.screen.blit(self.tint(t.last_move), self.sq_rect(sq))
        if self.selected is not None:
            rect = self.sq_rect(self.selected)
            self.screen.blit(self.tint(t.select), rect)
            pygame.draw.rect(self.screen, t.accent[:3], rect, 4)
        if g.outcome is not None and g.outcome.kind == "checkmate":
            self.screen.blit(self.glow(t.accent), self.sq_rect(g.pos.king_sq[g.outcome.winner]))
        elif g.outcome is not None:
            for color in (WHITE, BLACK):                         # draw: both kings glow neutral
                self.screen.blit(self.glow(t.muted), self.sq_rect(g.pos.king_sq[color]))
        if g.pos.in_check():
            self.screen.blit(self.glow(t.check), self.sq_rect(g.pos.king_sq[g.turn]))

        skip = set()
        if self.drag:
            skip.add(self.drag["sq"])
        if self.anim:
            skip.add(self.anim["to"])
        for sq, piece in enumerate(g.pos.board):
            if piece != "." and sq not in skip:
                self.screen.blit(self.piece_set.get(piece, SQ), self.sq_rect(sq))

        for m in self.targets:                                   # legal-move hints
            rect = self.sq_rect(m.to)
            layer = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
            if g.pos.board[m.to] != "." or (g.pos.board[m.frm] in "Pp" and m.to == g.pos.ep):
                pygame.draw.circle(layer, (*t.capture[:3], 215), (SQ // 2, SQ // 2), SQ // 2 - 3, 6)
            else:
                pygame.draw.circle(layer, t.dot if len(t.dot) == 4 else (*t.dot, 110), (SQ // 2, SQ // 2), 11)
            self.screen.blit(layer, rect)

        if self.anim:
            a = self.anim
            k = min(1.0, (time.monotonic() - a["t0"]) / a["dur"])
            k = 1 - (1 - k) ** 3
            p0, p1 = self.sq_rect(a["frm"]).topleft, self.sq_rect(a["to"]).topleft
            pos = (p0[0] + (p1[0] - p0[0]) * k, p0[1] + (p1[1] - p0[1]) * k)
            self.screen.blit(self.piece_set.get(a["piece"], SQ), pos)
        if self.drag:
            piece = g.pos.board[self.drag["sq"]]
            x, y = self.drag["pos"]
            self.screen.blit(self.piece_set.get(piece, SQ), (x - SQ // 2, y - SQ // 2))

    # ------------------------------------------------------------- sidebar
    def _draw_sidebar(self) -> None:
        t, g = self.theme, self.game
        x = SIDE_X
        self.text(APP_NAME, (x, 18), 28, t.text, True)
        self.text(t.tagline, (x, 52), 14, t.muted)

        # status card
        card = pygame.Rect(x, 84, SIDE_W, 70)
        self.rrect(card, t.panel, 12)
        if self.is_thinking():
            dots = "." * (int(time.monotonic() * 3) % 4)
            status, color = f"Computer is thinking{dots}", t.text
        else:
            status = g.status()
            color = t.check if (g.pos.in_check() and g.outcome is None) else (t.accent if g.outcome else t.text)
        pygame.draw.rect(self.screen, (t.check if g.pos.in_check() and g.outcome is None else t.accent)[:3],
                         (card.x, card.y + 10, 5, card.h - 20), border_radius=3)
        self.text(status, (card.x + 18, card.y + 12), 20, color, True)
        sub = f"Vs Computer \u00b7 {g.level.name}" if g.vs_computer else "Two players \u00b7 same screen"
        self.text(sub, (card.x + 18, card.y + 42), 13, t.muted)
        if self.is_thinking():
            seg = 70
            pos = int((time.monotonic() * 220) % (SIDE_W - 36 + seg)) - seg
            bar = pygame.Rect(card.x + 18, card.bottom - 9, SIDE_W - 36, 3)
            pygame.draw.rect(self.screen, t.panel_alt[:3], bar, border_radius=2)
            clip = pygame.Rect(max(bar.x, bar.x + pos), bar.y, 0, 3)
            clip.width = max(0, min(bar.right, bar.x + pos + seg) - clip.x)
            pygame.draw.rect(self.screen, t.accent[:3], clip, border_radius=2)

        opening = g.opening_name()
        self.text(f"Opening: {opening}" if opening else "Opening: \u2014", (x + 4, 164), 14, t.muted)

        # captured pieces
        cap = pygame.Rect(x, 190, SIDE_W, 74)
        self.rrect(cap, t.panel, 12)
        balance = g.material_balance()
        for i, (color, name) in enumerate(((WHITE, "White"), (BLACK, "Black"))):
            y = cap.y + 10 + i * 30
            self.text(name, (cap.x + 14, y + 4), 14, t.muted)
            for k, p in enumerate(g.captured_by(color)):
                self.screen.blit(self.piece_set.get(p, 26), (cap.x + 70 + k * 15, y))
            lead = balance if color == WHITE else -balance
            if lead > 0:
                self.text(f"+{lead}", (cap.right - 14, y + 4), 14, t.accent, True, "topright")

        # move list
        box = pygame.Rect(x, 274, SIDE_W, 254)
        self.rrect(box, t.panel, 12)
        self.text("MOVES", (box.x + 14, box.y + 10), 12, t.muted, True)
        pairs = g.move_pairs()
        rows = (box.h - 40) // 22
        max_scroll = max(0, len(pairs) - rows)
        self.move_scroll = min(self.move_scroll, max_scroll)
        first = max(0, len(pairs) - rows - self.move_scroll)
        for i, (num, white, black) in enumerate(pairs[first:first + rows]):
            y = box.y + 34 + i * 22
            if i % 2 == 0:
                self.rrect((box.x + 8, y - 2, box.w - 16, 22), (*t.panel_alt[:3], 120), 6)
            self.text(f"{num}.", (box.x + 16, y), 15, t.muted)
            newest = first + i == len(pairs) - 1
            self.text(white, (box.x + 56, y), 15, t.text, newest and black is None)
            if black:
                self.text(black, (box.x + 160, y), 15, t.text, newest)
        if not pairs:
            self.text("No moves yet", (box.centerx, box.centery), 15, t.muted, anchor="center")

        # buttons
        labels = [("New game", self.restart), ("Undo", self.do_undo), ("Flip", self._flip),
                  ("Theme", self.cycle_theme), ("Menu", self._to_menu), ("Quit", self._quit)]
        for i, (label, action) in enumerate(labels):
            rect = (x + (i % 3) * 102, 540 + (i // 3) * 46, 96, 40)
            self.button(rect, label, action, size=15,
                        enabled=not (label == "Undo" and not g.entries))
        self.text("N new   U undo   F flip   T theme   M menu", (x + SIDE_W // 2, 646), 12, t.muted,
                  anchor="center")

    def _flip(self) -> None:
        self.flipped = not self.flipped

    def _to_menu(self) -> None:
        self.mode = "menu"

    def _quit(self) -> None:
        self.running = False

    # ------------------------------------------------------------ overlays
    def _promo_slots(self):
        color = self.promo["color"]
        panel = pygame.Rect(0, 0, SQ * 4 + 40, SQ + 70)
        panel.center = BOARD_RECT.center
        slots = []
        by_piece = {m.promo: m for m in self.promo["moves"]}
        for i, key in enumerate("qrbn"):
            slots.append((pygame.Rect(panel.x + 20 + i * SQ, panel.y + 46, SQ, SQ), by_piece[key]))
        return slots

    def _draw_promotion(self) -> None:
        t = self.theme
        dim = pygame.Surface(BOARD_RECT.size, pygame.SRCALPHA)
        dim.fill((0, 0, 0, 150))
        self.screen.blit(dim, BOARD_RECT.topleft)
        panel = pygame.Rect(0, 0, SQ * 4 + 40, SQ + 70)
        panel.center = BOARD_RECT.center
        self.rrect(panel, t.panel, 16, 2, t.accent)
        self.text("Promote pawn to\u2026", (panel.centerx, panel.y + 24), 18, t.text, True, "center")
        mouse = pygame.mouse.get_pos()
        white = self.promo["color"] == WHITE
        for rect, move in self._promo_slots():
            self.rrect(rect.inflate(-6, -6), _mix(t.panel_alt, t.accent, 0.35 if rect.collidepoint(mouse) else 0), 12)
            letter = move.promo.upper() if white else move.promo
            self.screen.blit(self.piece_set.get(letter, SQ), rect)

    def _draw_end_banner(self) -> None:
        t, g = self.theme, self.game
        rect = pygame.Rect(0, 0, 440, 118)
        rect.center = BOARD_RECT.center
        self.rrect(rect, (*t.panel[:3], 238), 18, 2, t.accent)
        self.text(g.outcome.describe(), (rect.centerx, rect.y + 44), 26, t.text, True, "center")
        self.text("N: new game  \u00b7  M: menu  \u00b7  click board to hide", (rect.centerx, rect.y + 84), 14, t.muted,
                  anchor="center")

    # ----------------------------------------------------------- main loop
    def run(self) -> None:
        clock = pygame.time.Clock()
        while self.running:
            for event in pygame.event.get():
                self.handle_event(event)
            self.update()
            self.draw()
            pygame.display.flip()
            clock.tick(60)
        self.cancel_ai()
        pygame.quit()
