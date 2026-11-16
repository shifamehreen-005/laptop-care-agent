"""Read a folder and describe each file.

Read-only: this module never moves, renames, or writes anything.
"""

import csv
import hashlib
import logging
import sys
from datetime import datetime
from pathlib import Path

# Preview failures are stored on the file, so the PDF library should stay quiet.
logging.getLogger("pypdf").setLevel(logging.ERROR)

from config import CATEGORIES, TEST_FOLDER

PREVIEW_CHARS = 300
# Review is a place the agent uses. Anything else was made by the user.
AGENT_FOLDERS = tuple(CATEGORIES) + ("Review",)


def agent_folder_names() -> list[str]:
    """Default folders plus renamed and custom labels from folders.json."""
    names = list(AGENT_FOLDERS)
    seen = {name.casefold() for name in names}
    try:
        from folders import saved_names

        extra = saved_names()
    except OSError:
        extra = []
    for name in extra:
        if not name or name.casefold() in seen or name == "_safe_to_remove":
            continue
        seen.add(name.casefold())
        names.append(name)
    return names


def folders_to_read(folder: Path) -> list[str]:
    """Every folder under the one the user chose. Not a fixed name list.

    _safe_to_remove is the holding area, so it is not scanned again.
    """
    names = []
    seen = set()

    def walk(current: Path) -> None:
        try:
            entries = list(current.iterdir())
        except OSError:
            return
        for item in sorted(entries, key=lambda entry: entry.name.lower()):
            if not item.is_dir() or item.name.startswith(".") or item.name == "_safe_to_remove":
                continue
            if not stays_in(folder, item):
                continue
            try:
                resolved = item.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            names.append(item.relative_to(folder).as_posix())
            walk(item)

    walk(folder)
    return names


def scan_folder(path) -> list[dict]:
    """Describe every file under the chosen folder.

    One unreadable file does not stop the scan. _safe_to_remove is not read.
    """
    folder = Path(path)
    assert_readable(folder)
    records = []
    for item in sorted(folder.iterdir(), key=lambda entry: entry.name.lower()):
        if item.is_file():
            records.append(describe_file(folder, item, ""))
    for name in folders_to_read(folder):
        sub = folder / name
        if not sub.is_dir() or not stays_in(folder, sub):
            continue
        for item in sorted(sub.iterdir(), key=lambda entry: entry.name.lower()):
            if item.is_file():
                records.append(describe_file(folder, item, name))
    mark_duplicates(records)
    return records


def stays_in(root: Path, path: Path) -> bool:
    base = root.resolve()
    try:
        candidate = path.resolve()
    except OSError:
        return False
    return candidate == base or base in candidate.parents


def assert_readable(folder: Path) -> None:
    # A scan must not open the real Downloads, Desktop, or Documents folders.
    if not folder.is_dir():
        raise NotADirectoryError(f"{folder} is not a folder.")
    candidate = folder.resolve()
    home = Path.home()
    blocked = [home / name for name in ("Downloads", "Desktop", "Documents")]
    blocked.extend(home.glob("OneDrive*/Downloads"))
    blocked.extend(home.glob("OneDrive*/Desktop"))
    blocked.extend(home.glob("OneDrive*/Documents"))
    for root in blocked:
        root = root.resolve()
        if candidate == root or root in candidate.parents:
            raise ValueError(
                f"Refusing to scan {candidate}. "
                "Only the test folder is allowed, never real Downloads, Desktop, or Documents."
            )


def describe_file(root: Path, item: Path, folder_name: str) -> dict:
    record = {
        "name": item.name,
        "path": str(item),
        "folder": folder_name,
        "extension": item.suffix.lower(),
        "size_bytes": None,
        "modified": None,
        "added": None,
        "sha256": None,
        "preview_text": "",
        "is_duplicate": False,
        "duplicate_of": "",
    }
    # A link can point outside the folder. Do not follow it.
    resolved = item.resolve()
    expected = root.resolve() if not folder_name else (root.resolve() / folder_name).resolve()
    if resolved.parent != expected:
        record["error"] = "File resolves outside the folder."
        return record
    try:
        info = item.stat()
        record["size_bytes"] = info.st_size
        record["modified"] = datetime.fromtimestamp(info.st_mtime).isoformat(timespec="seconds")
        record["added"] = arrival_time(info)
        record["sha256"] = sha256_file(item)
    except OSError as err:
        record["error"] = str(err)
        return record
    try:
        record["preview_text"] = preview_text(item)
    except Exception as err:
        # The bytes were readable, so keep the hash and only note the preview.
        record["error"] = f"Could not read preview: {err}"
    return record


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# These are not text. Everything else is opened as text so the agent can read inside.
BINARY_TYPES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".heif",
    ".mp4", ".mkv", ".mov", ".avi", ".mp3", ".wav", ".flac",
    ".zip", ".rar", ".7z", ".exe", ".msi", ".dll", ".bin",
}


def text_sample(path: Path) -> str:
    """Start, middle, and end of a file. Used by Ask an agent, not by the normal scan."""
    extension = path.suffix.lower()
    if extension in BINARY_TYPES:
        return ""
    if extension == ".pdf":
        raw = pdf_preview(path, limit=2000)
    elif extension == ".docx":
        raw = docx_preview(path, limit=2000)
    else:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            raw = handle.read(8000)
        if "\x00" in raw:
            return ""
    return windows(raw)


def windows(text: str) -> str:
    """Three short slices. The topic is often a heading, a middle paragraph, or a closing line."""
    words = " ".join((text or "").split())
    if len(words) <= 500:
        return words
    middle = max(0, len(words) // 2 - 70)
    return (
        f"start: {words[:220]} | "
        f"mid: {words[middle:middle + 140]} | "
        f"end: {words[-160:]}"
    )


def preview_text(path: Path) -> str:
    extension = path.suffix.lower()
    if extension == ".pdf":
        return pdf_preview(path)
    if extension == ".docx":
        return docx_preview(path)
    if extension in BINARY_TYPES:
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        text = handle.read(PREVIEW_CHARS)
    # A stray binary file is full of nulls. Skip it instead of sending garbage.
    if "\x00" in text:
        return ""
    return text


def pdf_preview(path: Path, limit: int = PREVIEW_CHARS) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    total = 0
    for page in reader.pages:
        piece = page.extract_text() or ""
        parts.append(piece)
        total += len(piece)
        if total >= limit:
            break
    return "".join(parts)[:limit]


def docx_preview(path: Path, limit: int = PREVIEW_CHARS) -> str:
    from docx import Document

    document = Document(str(path))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    return text[:limit]


def arrival_time(info) -> str:
    """When the file arrived. Windows creation time, or the modified time if that is missing."""
    birth = getattr(info, "st_birthtime", None)
    stamp = info.st_mtime if not birth else birth
    return datetime.fromtimestamp(stamp).isoformat(timespec="seconds")


def is_copy_style(name: str) -> bool:
    # Windows writes "notes (1).docx" and "notes - Copy.docx" when it copies a file.
    stem = Path(name).stem
    if stem.endswith(" - Copy"):
        return True
    if not stem.endswith(")"):
        return False
    opened = stem.rfind(" (")
    if opened == -1:
        return False
    number = stem[opened + 2 : -1]
    return number.isdigit()


def mark_duplicates(records: list[dict]) -> None:
    """Same bytes anywhere in the scan are one group. Copy-style names lose to a plain name."""
    groups: dict[str, list[dict]] = {}
    for record in records:
        digest = record.get("sha256")
        if not digest:
            continue
        groups.setdefault(digest, []).append(record)
    for group in groups.values():
        if len(group) < 2:
            continue
        plain = [record for record in group if not is_copy_style(record.get("name") or "")]
        # No plain name: the oldest copy-style file is kept. Otherwise every copy-style name loses.
        pool = plain or group
        pool.sort(key=keep_key)
        keeper = pool[0]
        kept = keeper.get("name") or ""
        for record in group:
            record["is_duplicate"] = record is not keeper
            record["duplicate_of"] = "" if record is keeper else kept


def keep_key(record: dict) -> tuple:
    # Oldest arrival, then oldest edit, then the name that comes first alphabetically.
    return (
        record.get("added") or "",
        record.get("modified") or "",
        (record.get("name") or "").lower(),
    )


def warn_unlabeled(records: list[dict]) -> None:
    labels = Path(TEST_FOLDER).parent / "labels.csv"
    known: set[str] = set()
    if labels.is_file():
        with labels.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                name = (row.get("filename") or "").strip()
                if name:
                    known.add(name)
    missing = [record["name"] for record in records if record["name"] not in known]
    if not missing:
        return
    print("Warning: no label for:")
    for name in missing:
        print(f"  {name}")


def main() -> None:
    records = scan_folder(TEST_FOLDER)
    total_size = sum(record["size_bytes"] or 0 for record in records)
    duplicates = sum(1 for record in records if record["is_duplicate"])
    print(f"Files: {len(records)}")
    print(f"Total size: {total_size} bytes")
    print(f"Duplicates: {duplicates}")
    warn_unlabeled(records)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as err:
        sys.exit(str(err))
