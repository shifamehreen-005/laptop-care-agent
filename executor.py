"""Move files for an approved plan, and put them back from the undo log.

Files are never deleted. A file whose name is taken is given " (2)", then " (3)".
An empty folder this run created is removed on undo.
"""

import argparse
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from config import TEST_FOLDER
from planner import build_plan, summary
from scanner import assert_readable, scan_folder


def apply_plan(plan, approved, log_path, suggestions=False):
    """Move each approved file. Returns the run id, or None when nothing was approved."""
    # The main plan and the suggested fixes are separate yeses. Default is neither.
    if approved is not True and suggestions is not True:
        print("Not approved. Nothing was moved.")
        return None
    folder = Path(TEST_FOLDER).resolve()
    assert_readable(folder)
    run_id = uuid.uuid4().hex
    log_path = Path(log_path)
    for action in plan:
        if action.get("suggested"):
            if suggestions is not True:
                continue
        elif approved is not True:
            continue
        move_one(folder, action, run_id, log_path)
    return run_id


def undo(run_id, log_path) -> None:
    """Reverse one run, newest move first. A missing file is skipped."""
    folder = Path(TEST_FOLDER).resolve()
    assert_readable(folder)
    records = moves_for_run(Path(log_path), run_id)
    moves = [record for record in records if "from" in record or "to" in record]
    created = [record for record in records if record.get("created_dir")]
    for record in reversed(moves):
        reverse_one(folder, record)
    # Files are back. Remove only folders this run created, and only when empty.
    remove_created_dirs(folder, created)


def move_one(folder: Path, action: dict, run_id: str, log_path: Path) -> None:
    name = action.get("name") or ""
    destination = action.get("destination") or ""
    current = action.get("folder") or ""
    # Duplicates are already marked with destination _safe_to_remove. Move, never delete.
    if not single_name(name) or not single_name(destination) or (current and not single_name(current)):
        print(f"Skipped {name!r}. The path must stay inside the test folder.")
        return
    src = folder / current / name if current else folder / name
    if not src.is_file() or not stays_inside(folder, src):
        print(f"Missing, skipped: {name}")
        return
    target_dir = folder / destination
    if not stays_inside(folder, target_dir):
        print(f"Skipped {name!r}. The path must stay inside the test folder.")
        return
    created = not target_dir.exists()
    target_dir.mkdir(exist_ok=True)
    if created:
        append_created_dir(log_path, run_id, folder, target_dir)
    dest = unique_name(target_dir / name)
    src.rename(dest)
    append_log(log_path, run_id, folder, src, dest)


def reverse_one(folder: Path, record: dict) -> None:
    src = inside_path(folder, record.get("to") or "")
    dest = inside_path(folder, record.get("from") or "")
    if src is None or dest is None:
        print("Skipped a move that leaves the test folder.")
        return
    if not src.is_file():
        print(f"Missing, skipped: {record.get('to')}")
        return
    dest.parent.mkdir(exist_ok=True)
    src.rename(unique_name(dest))


def unique_name(path: Path) -> Path:
    """Next free name. Never replaces a file that is already there."""
    if not path.exists():
        return path
    number = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not candidate.exists():
            return candidate
        number += 1


def append_log(log_path: Path, run_id: str, folder: Path, src: Path, dest: Path) -> None:
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
        "from": src.relative_to(folder).as_posix(),
        "to": dest.relative_to(folder).as_posix(),
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def append_created_dir(log_path: Path, run_id: str, folder: Path, target_dir: Path) -> None:
    record = {
        "run_id": run_id,
        "created_dir": target_dir.relative_to(folder).as_posix(),
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def remove_created_dirs(folder: Path, records: list[dict]) -> None:
    """Newest folder first. os.rmdir refuses a folder that still has anything in it."""
    for record in reversed(records):
        raw = record.get("created_dir")
        if not isinstance(raw, str):
            continue
        path = inside_path(folder, raw)
        if path is None or path == folder or path.is_symlink() or not path.is_dir():
            continue
        try:
            os.rmdir(path)
        except OSError:
            if path.is_dir() and any(path.iterdir()):
                print(f"Not empty, left in place: {raw}")


def moves_for_run(log_path: Path, run_id) -> list[dict]:
    if not log_path.is_file():
        return []
    moves = []
    with log_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("run_id") == run_id:
                moves.append(record)
    return moves


def single_name(name: str) -> bool:
    # A destination like "..\\Desktop" would leave the test folder.
    if not name or name in {".", ".."}:
        return False
    return "/" not in name and "\\" not in name and Path(name).name == name


def stays_inside(folder: Path, path: Path) -> bool:
    candidate = path.resolve()
    return candidate == folder or folder in candidate.parents


def inside_path(folder: Path, value: str) -> Path | None:
    if not value:
        return None
    raw = Path(value)
    candidate = raw if raw.is_absolute() else folder / raw
    if not stays_inside(folder, candidate):
        return None
    return candidate


def log_path_for_folder() -> Path:
    # Keep the log beside the test folder. A file inside it would be planned and moved.
    return Path(TEST_FOLDER).resolve().parent / "undo.log"


def command_apply(log_path: Path) -> None:
    plan = build_plan(scan_folder(TEST_FOLDER))
    print(summary(plan))
    answer = input("Type yes to continue: ")
    approved = answer.strip() == "yes"
    suggested = [action for action in plan if action.get("suggested")]
    # Empty, "no", or anything other than yes leaves the suggested files where they are.
    apply_suggestions = False
    if suggested:
        follow = input(f"Also apply {len(suggested)} suggested fixes? (yes/no): ")
        apply_suggestions = follow.strip() == "yes"
    apply_plan(plan, approved, log_path, suggestions=apply_suggestions)


def command_undo(log_path: Path) -> None:
    run_id = latest_run_id(log_path)
    if run_id is None:
        print("No runs to undo.")
        return
    undo(run_id, log_path)


def command_runs(log_path: Path) -> None:
    runs = runs_in_log(log_path)
    if not runs:
        print("No runs yet.")
        return
    for run in runs:
        count = run["count"]
        noun = "file" if count == 1 else "files"
        print(f"{run['timestamp']}  {run['run_id']}  {count} {noun}")


def runs_in_log(log_path: Path) -> list[dict]:
    """One entry per run, oldest first. The last entry is the most recent run."""
    if not log_path.is_file():
        return []
    order = []
    counts: dict[str, int] = {}
    started: dict[str, str] = {}
    with log_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            run_id = record.get("run_id")
            if not run_id:
                continue
            if run_id not in counts:
                order.append(run_id)
                counts[run_id] = 0
                started[run_id] = ""
            timestamp = record.get("timestamp") or ""
            if timestamp and not started[run_id]:
                started[run_id] = timestamp
            # A created folder is not a moved file.
            if "created_dir" in record and "from" not in record:
                continue
            counts[run_id] += 1
    return [
        {"run_id": run_id, "timestamp": started[run_id], "count": counts[run_id]}
        for run_id in order
    ]


def latest_run_id(log_path: Path):
    runs = runs_in_log(log_path)
    if not runs:
        return None
    return runs[-1]["run_id"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply an approved plan, or undo it.")
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument(
        "--apply",
        action="store_true",
        help='Build a plan, print the summary, and ask "Type yes to continue".',
    )
    commands.add_argument(
        "--undo",
        action="store_true",
        help="Undo the most recent run.",
    )
    commands.add_argument(
        "--runs",
        action="store_true",
        help="List past runs.",
    )
    args = parser.parse_args()
    log_path = log_path_for_folder()
    if args.apply:
        command_apply(log_path)
    elif args.undo:
        command_undo(log_path)
    else:
        command_runs(log_path)


if __name__ == "__main__":
    main()
