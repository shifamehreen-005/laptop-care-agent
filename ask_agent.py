"""Turn a plain ask into a new set of folders. Nothing moves until Approve."""

from __future__ import annotations

from planner import DUPLICATE_FOLDER

# What the review screen offers as one-click asks.
SAMPLES = (
    "Sort by what's inside",
    "Group by file type",
)

# Known extensions → folder name. Anything else uses "PDF files", "HTML files", …
TYPE_NAMES = {
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".jsx": "JavaScript",
    ".tsx": "TypeScript",
    ".py": "Python",
    ".java": "Java",
    ".c": "C",
    ".cpp": "C++",
    ".h": "Headers",
    ".cs": "C Sharp",
    ".php": "PHP",
    ".rb": "Ruby",
    ".go": "Go",
    ".rs": "Rust",
    ".pdf": "PDFs",
    ".doc": "Documents",
    ".docx": "Documents",
    ".txt": "Text",
    ".md": "Text",
    ".rtf": "Documents",
    ".png": "Images",
    ".jpg": "Images",
    ".jpeg": "Images",
    ".gif": "Images",
    ".webp": "Images",
    ".heic": "Images",
    ".bmp": "Images",
    ".tif": "Images",
    ".tiff": "Images",
    ".mp4": "Videos",
    ".mkv": "Videos",
    ".mov": "Videos",
    ".avi": "Videos",
    ".mp3": "Audio",
    ".wav": "Audio",
    ".flac": "Audio",
    ".zip": "Archives",
    ".rar": "Archives",
    ".7z": "Archives",
    ".exe": "Installers",
    ".msi": "Installers",
    ".csv": "Spreadsheets",
    ".xlsx": "Spreadsheets",
    ".xls": "Spreadsheets",
    ".pptx": "Slides",
    ".ppt": "Slides",
}


def pick_mode(text: str) -> str:
    """Group by extension is the one fixed rule. Every other ask goes to the model."""
    ask = (text or "").casefold()
    if any(word in ask for word in ("file type", "extension", "by type", "by extension")):
        return "type"
    return "judge"


def apply_ask(
    plan: list[dict],
    files: list[dict],
    ask: str,
    name_for_file=None,
) -> tuple[list[dict], list[dict], str]:
    """Return (new labels, updated plan, short note). name_for_file(record) is used for subject."""
    mode = pick_mode(ask)
    records = {f"{item.get('folder') or ''}/{item.get('name') or ''}": item for item in files}
    if mode == "judge":
        mapping = {}
        for action in plan:
            if action.get("destination") == DUPLICATE_FOLDER:
                continue
            record = records.get(action_id(action)) or {}
            name = ""
            if name_for_file is not None:
                try:
                    name = (name_for_file(record) or "").strip()
                except Exception:
                    name = ""
            # No answer keeps the folder from the scan. It does not dump the file into Review.
            if not name:
                name = action.get("destination") or "Review"
            mapping[action_id(action)] = name
        note = "Sorted from what's inside each file, using qwen2.5:3b."
    else:
        mapping = {
            action_id(action): type_folder(records.get(action_id(action)) or {})
            for action in plan
        }
        note = "Sorted by file type. Every extension gets a folder."
    labels, plan = rebuild(plan, mapping)
    return labels, plan, note


def type_folder(record: dict) -> str:
    extension = (record.get("extension") or "").lower()
    if not extension:
        name = record.get("name") or ""
        if "." in name:
            extension = "." + name.rsplit(".", 1)[-1].lower()
    if not extension:
        return "No extension"
    if extension in TYPE_NAMES:
        return TYPE_NAMES[extension]
    stem = extension.lstrip(".")
    return f"{stem.upper()} files"


def rebuild(plan: list[dict], mapping: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Make one label per folder name and point every file at it. Duplicates stay put."""
    names: list[str] = []
    seen: set[str] = set()
    for action in plan:
        if action.get("destination") == DUPLICATE_FOLDER and not action.get("leave"):
            continue
        dest = mapping.get(action_id(action)) or "Review"
        key = dest.casefold()
        if key not in seen:
            seen.add(key)
            names.append(dest)
    labels = []
    for name in names:
        labels.append(
            {
                "key": _key(name, labels),
                "name": name,
                "description": "From Ask an agent",
                "source": "yours",
            }
        )
    by_name = {label["name"].casefold(): label for label in labels}
    for action in plan:
        if action.get("destination") == DUPLICATE_FOLDER and not action.get("leave"):
            action["label_key"] = ""
            action.pop("suggested", None)
            continue
        dest = mapping.get(action_id(action)) or "Review"
        label = by_name[dest.casefold()]
        action["destination"] = label["name"]
        action["label_key"] = label["key"]
        action["leave"] = False
        action["source"] = "ask"
        action["reason"] = "Ask an agent"
        action["moved_by_you"] = False
        action.pop("suggested", None)
        action.pop("previous", None)
    return labels, plan


def action_id(action: dict) -> str:
    return f"{action.get('folder') or ''}/{action.get('name') or ''}"


def _key(name: str, labels: list[dict]) -> str:
    base = "".join(ch if ch.isalnum() else "-" for ch in name.casefold()).strip("-") or "label"
    taken = {label.get("key") for label in labels}
    key = base
    number = 2
    while key in taken:
        key = f"{base}-{number}"
        number += 1
    return key
