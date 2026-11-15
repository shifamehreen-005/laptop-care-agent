"""Destination labels saved in folders.json.

A renamed default keeps its key, so the old rules still point at it.
"""

import json
import re
from pathlib import Path

from classifier import CATEGORY_DESCRIPTIONS
from config import CATEGORIES

FOLDERS_PATH = Path(__file__).resolve().with_name("folders.json")
MAX_NAME = 40
FORBIDDEN = set('\\/:*?"<>|')
RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
BLOCKED = {"_safe_to_remove"}


def default_labels() -> list[dict]:
    labels = []
    for name in list(CATEGORIES) + ["Review"]:
        labels.append(
            {
                "key": name,
                "name": name,
                "description": CATEGORY_DESCRIPTIONS.get(name, "files to look over before filing"),
                "source": "default",
            }
        )
    return labels


def load_labels() -> list[dict]:
    """Read folders.json, or write the defaults the first time."""
    if not FOLDERS_PATH.is_file():
        labels = default_labels()
        save_labels(labels)
        return labels
    data = json.loads(FOLDERS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("labels")
    # An empty list is allowed: the user removed every label.
    labels = []
    for item in data:
        label = clean_label(item)
        if label:
            labels.append(label)
    return labels


def save_labels(labels: list[dict]) -> None:
    FOLDERS_PATH.write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")


def reset_labels() -> list[dict]:
    labels = default_labels()
    save_labels(labels)
    return labels


def saved_names() -> list[str]:
    """Names already on disk. Does not create the file, so a scan stays read-only."""
    if not FOLDERS_PATH.is_file():
        return []
    try:
        data = json.loads(FOLDERS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    names = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def clean_label(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    key = str(item.get("key") or "").strip()
    name = str(item.get("name") or "").strip()
    if not key or not name:
        return None
    source = item.get("source") or "yours"
    if source not in {"default", "suggested", "yours"}:
        source = "yours"
    label = {
        "key": key,
        "name": name,
        "description": str(item.get("description") or ""),
        "source": source,
    }
    # A label you made stays for the next scan only after Approve.
    if item.get("approved"):
        label["approved"] = True
    return label


def validate_name(name: str, labels: list[dict], ignore_key: str = "") -> str:
    """A sentence the screen can show, or "" when the name is allowed."""
    cleaned = (name or "").strip()
    if not cleaned:
        return "Type a name."
    if len(cleaned) > MAX_NAME:
        return "Use 40 characters or fewer."
    if any(char in FORBIDDEN for char in cleaned):
        return "That name has a character Windows doesn't allow."
    if cleaned.endswith(".") or cleaned.endswith(" "):
        return "That name can't end with a space or a period."
    stem = cleaned.split(".", 1)[0]
    blocked = {item.casefold() for item in BLOCKED}
    if cleaned.casefold() in blocked or stem.casefold() in blocked:
        return "That name is reserved."
    if stem.upper() in RESERVED or cleaned.upper() in RESERVED:
        return "Windows reserves that name."
    for label in labels:
        if label.get("key") == ignore_key:
            continue
        if (label.get("name") or "").casefold() == cleaned.casefold():
            return "There's already a label with that name."
    return ""


def new_key(name: str, labels: list[dict]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").casefold()).strip("-") or "label"
    taken = {label.get("key") for label in labels}
    key = base
    number = 2
    while key in taken:
        key = f"{base}-{number}"
        number += 1
    return key
