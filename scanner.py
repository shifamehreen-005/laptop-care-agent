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

from config import TEST_FOLDER

PREVIEW_CHARS = 300


def scan_folder(path) -> list[dict]:
    """Describe each file in path. One unreadable file does not stop the scan."""
    folder = Path(path)
    assert_readable(folder)
    records = []
    for item in sorted(folder.iterdir(), key=lambda entry: entry.name.lower()):
        if not item.is_file():
            continue
        records.append(describe_file(folder, item))
    mark_duplicates(records)
    return records


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


def describe_file(folder: Path, item: Path) -> dict:
    record = {
        "name": item.name,
        "path": str(item),
        "extension": item.suffix.lower(),
        "size_bytes": None,
        "modified": None,
        "sha256": None,
        "preview_text": "",
        "is_duplicate": False,
    }
    # A link can point outside the folder. Do not follow it.
    resolved = item.resolve()
    if resolved.parent != folder.resolve():
        record["error"] = "File resolves outside the folder."
        return record
    try:
        info = item.stat()
        record["size_bytes"] = info.st_size
        record["modified"] = datetime.fromtimestamp(info.st_mtime).isoformat(timespec="seconds")
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


def preview_text(path: Path) -> str:
    extension = path.suffix.lower()
    if extension == ".txt":
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(PREVIEW_CHARS)
    if extension == ".pdf":
        return pdf_preview(path)
    if extension == ".docx":
        return docx_preview(path)
    return ""


def pdf_preview(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    total = 0
    for page in reader.pages:
        piece = page.extract_text() or ""
        parts.append(piece)
        total += len(piece)
        if total >= PREVIEW_CHARS:
            break
    return "".join(parts)[:PREVIEW_CHARS]


def docx_preview(path: Path) -> str:
    from docx import Document

    document = Document(str(path))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    return text[:PREVIEW_CHARS]


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
    # Keep a plain name, such as notes_final.docx, and set aside "notes_final (1).docx".
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
        # Several plain names: keep the oldest. All copies: keep the oldest copy.
        pool = plain or group
        pool.sort(key=lambda record: (record.get("modified") or "", (record.get("name") or "").lower()))
        keeper = pool[0]
        for record in group:
            record["is_duplicate"] = record is not keeper


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
