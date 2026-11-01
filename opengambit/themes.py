"""Theme loading. Themes are pure data (JSON) so re-branding needs no code."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_PATH = Path(__file__).with_name("data") / "themes.json"
Color = Tuple[int, ...]

REQUIRED_COLORS = (
    "bg", "panel", "panel_alt", "text", "muted", "accent", "accent_text",
    "light_sq", "dark_sq", "white_fill", "white_line", "black_fill", "black_line",
    "last_move", "select", "dot", "capture", "check",
)


def parse_color(text: str) -> Color:
    text = text.lstrip("#")
    if len(text) not in (6, 8):
        raise ValueError(f"Bad colour {text!r}; use #RRGGBB or #RRGGBBAA")
    return tuple(int(text[i:i + 2], 16) for i in range(0, len(text), 2))


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    tagline: str
    kind: str
    inspired_by: Optional[str]
    colors: Dict[str, Color]

    def __getattr__(self, item: str) -> Color:        # theme.accent, theme.light_sq ...
        try:
            return self.__dict__["colors"][item]
        except KeyError:
            raise AttributeError(item) from None

    @property
    def subtitle(self) -> str:
        return f"{self.inspired_by}-inspired colours" if self.inspired_by else "Built-in theme"

    @property
    def is_dark(self) -> bool:
        r, g, b = self.colors["bg"][:3]
        return (r * 299 + g * 587 + b * 114) / 1000 < 128


def load_themes(path: Optional[Path] = None) -> List[Theme]:
    data = json.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
    themes = []
    for entry in data["themes"]:
        missing = [k for k in REQUIRED_COLORS if k not in entry["colors"]]
        if missing:
            raise ValueError(f"Theme {entry['id']!r} is missing colours: {missing}")
        themes.append(Theme(
            id=entry["id"], name=entry["name"], tagline=entry.get("tagline", ""),
            kind=entry.get("kind", "custom"), inspired_by=entry.get("inspired_by"),
            colors={k: parse_color(v) for k, v in entry["colors"].items()},
        ))
    return themes
