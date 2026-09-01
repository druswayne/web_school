from __future__ import annotations

import json
from pathlib import Path

from .config import INSTANCE_DIR

_DIR = INSTANCE_DIR / "theory_play"


def empty_deck() -> dict:
    return {"selection": [], "order": [], "done_ids": [], "round": 1}


def _path(user_id: int) -> Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    return _DIR / f"{int(user_id)}.json"


def load_deck(user_id: int) -> dict:
    path = _path(user_id)
    if not path.is_file():
        return empty_deck()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_deck()
    if not isinstance(data, dict):
        return empty_deck()
    return {
        "selection": [str(x) for x in (data.get("selection") or []) if x],
        "order": [str(x) for x in (data.get("order") or []) if x],
        "done_ids": [str(x) for x in (data.get("done_ids") or []) if x],
        "round": int(data.get("round") or 1),
    }


def save_deck(user_id: int, deck: dict) -> None:
    path = _path(user_id)
    tmp = path.with_suffix(".json.tmp")
    payload = json.dumps(
        {
            "selection": list(deck.get("selection") or []),
            "order": list(deck.get("order") or []),
            "done_ids": list(deck.get("done_ids") or []),
            "round": int(deck.get("round") or 1),
        },
        ensure_ascii=False,
    )
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
