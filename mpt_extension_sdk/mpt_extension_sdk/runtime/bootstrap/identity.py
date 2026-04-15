import json
from pathlib import Path
from typing import Any


def load_identity(path: Path) -> dict[str, Any]:
    """Load identity payload from disk."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as identity_file:
        payload = json.load(identity_file)
    if not isinstance(payload, dict):
        return {}
    return payload


def save_identity(path: Path, identity: dict[str, Any]) -> None:
    """Persist identity payload to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as identity_file:
        json.dump(identity, identity_file)
