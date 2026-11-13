"""Append one label for a file that is already in the test folder."""

import csv
import sys
from pathlib import Path

from config import CATEGORIES, TEST_FOLDER
from scanner import assert_readable


def labels_path() -> Path:
    return Path(TEST_FOLDER).parent / "labels.csv"


def labeled_names(path: Path) -> set[str]:
    if not path.is_file() or path.stat().st_size == 0:
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "filename" not in reader.fieldnames:
            sys.exit(f"{path} has no filename column.")
        return {row["filename"] for row in reader if row.get("filename")}


def add_label(filename: str, category: str) -> None:
    # A path like ..\secret.pdf must not be accepted as a file name.
    if not filename or filename != Path(filename).name:
        sys.exit("Give the file name only, not a path.")
    folder = Path(TEST_FOLDER)
    assert_readable(folder)
    if not (folder / filename).is_file():
        sys.exit(f"{filename} is not in {folder}.")
    if category not in CATEGORIES:
        sys.exit(f"{category} is not a category.")
    labels = labels_path()
    if filename in labeled_names(labels):
        sys.exit(f"{filename} already has a label.")
    # Append only. An existing labels.csv is never rewritten.
    write_header = (not labels.exists()) or labels.stat().st_size == 0
    with labels.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(["filename", "true_category"])
        writer.writerow([filename, category])


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("Usage: python add_label.py <filename> <category>")
    add_label(sys.argv[1], sys.argv[2])
    print(f"Added {sys.argv[1]},{sys.argv[2]}")


if __name__ == "__main__":
    main()
