"""Append one label for a file that is already in the test folder (or another folder given with --folder)."""

import argparse
import csv
import sys
from pathlib import Path

from config import CATEGORIES, TEST_FOLDER
from scanner import assert_readable


def labels_path(folder=TEST_FOLDER) -> Path:
    return Path(folder).parent / "labels.csv"


def labeled_names(path: Path) -> set[str]:
    if not path.is_file() or path.stat().st_size == 0:
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "filename" not in reader.fieldnames:
            sys.exit(f"{path} has no filename column.")
        return {row["filename"] for row in reader if row.get("filename")}


def add_label(filename: str, category: str, folder=TEST_FOLDER, labels: Path | None = None) -> None:
    # A path like ..\secret.pdf must not be accepted as a file name.
    if not filename or filename != Path(filename).name:
        sys.exit("Give the file name only, not a path.")
    folder = Path(folder)
    assert_readable(folder)
    if not (folder / filename).is_file():
        sys.exit(f"{filename} is not in {folder}.")
    if category not in CATEGORIES:
        sys.exit(f"{category} is not a category.")
    labels = Path(labels) if labels else labels_path(folder)
    # The answer key must not become one of the files being graded.
    if folder.resolve() in labels.resolve().parents:
        sys.exit("Keep the labels file outside the folder being labeled.")
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
    parser = argparse.ArgumentParser(description="Append one label to labels.csv.")
    parser.add_argument("filename", help="File name only, not a path.")
    parser.add_argument("category", help=f"One of: {', '.join(CATEGORIES)}")
    parser.add_argument("--folder", default=TEST_FOLDER, help=f"Folder the file is in (default: {TEST_FOLDER}).")
    parser.add_argument("--labels", default=None, help="Labels file (default: labels.csv next to the folder).")
    args = parser.parse_args()
    add_label(args.filename, args.category, args.folder, args.labels)
    print(f"Added {args.filename},{args.category}")


if __name__ == "__main__":
    main()
