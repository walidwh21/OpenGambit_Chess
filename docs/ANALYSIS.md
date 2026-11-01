# Analysis of the original project and what changed

## What the original was

A single-file (~1,750 lines) Python 2 / pygame chess game with a negamax + alpha-beta computer
opponent, a pickled opening book and image assets. About 42 % of its lines were comments, and
the first 153 lines (before the first import) were a personal work log, credits and design notes.

| Area | Original approach | Problems found |
|---|---|---|
| Runtime | Python 2 only (`itervalues`, `isAlive`, `/` on ints used as indices, `pickle.loads(str)`) | Does not run on Python 3 |
| State | ~67 module-level assignments, mutated from one giant `while` loop | Untestable, hard to extend |
| Rules | Board as list-of-lists of 2-char strings | Pawns **always** auto-queen; draw-by-repetition checked `>=3` over a *shared mutable default* `history={}`; en-passant target computed with `/` (integer division only under Python 2) |
| Move generation | Clone + `deepcopy` of the whole position for every candidate move | Very slow search |
| AI | Fixed depth 3, no move ordering, no quiescence | Horizon effect, weak tactics |
| Piece-square tables | Hand-typed; contained outliers such as `-90` and `+70` | Odd, accidental play |
| Opening book | Python-pickle file loaded with `pickle.loads` | Executes arbitrary code if the file is replaced |
| Assets | Windows-style paths (`'Media\\board.png'`), third-party board and piece sprites | Breaks on macOS/Linux; licensing unclear |
| Personal data | Author name, university ID, course number, instructor name, a promo URL and the window title | Must be removed before reuse |

## What the rewrite does differently

| Concern | New design |
|---|---|
| Architecture | Layered package: `engine`, `ai`, `book`, `game`, `themes` (no pygame) + `pieces`, `ui` |
| Python | 3.9+, type hints, `pathlib`, cross-platform paths |
| Board | Flat 64-cell FEN-style list; pre-computed ray / knight / king tables |
| Make / unmake | In-place with an undo stack, no deep copies |
| Rules coverage | Under-promotion with picker, correct repetition, fifty-move, insufficient material, SAN & FEN |
| Correctness proof | Matches published perft counts on five reference positions |
| Search | Iterative deepening under a time budget, TT, killer moves, MVV-LVA ordering, check extensions, quiescence |
| Evaluation | Tapered middlegame/endgame, **formula-generated** piece-square tables, passed / doubled / isolated pawns, bishop pair |
| Levels | Beginner (randomised), Casual, Club (depth 4), Expert (depth up to 6, 8 s cap) |
| Opening book | Human-editable JSON in SAN, plus opening names shown in the UI |
| UI | New menu, side panel, move list, captured pieces, promotion dialog, animation, undo, themes |
| Assets | None: pieces are drawn procedurally, so nothing third-party ships with the project |
| Branding | Everything user-visible comes from `themes.json` and one `APP_NAME` constant |
| Privacy | All personal names, IDs, course/instructor references, URLs and the old title removed |
| Quality | 33 automated tests, including simulated mouse input |

## Provenance note

The rewrite shares no source code, images or data files with the original; the architecture,
algorithms (negamax / alpha-beta / transposition tables are standard, public techniques), tables,
artwork, notation handling and UI were all written fresh. Only the high-level idea (a pygame chess
game with an alpha-beta opponent) is common to both.
