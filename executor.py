"""Move files for an approved plan, and put them back from the undo log.

A taken name becomes " (2)", then " (3)". An empty folder this run created is removed on undo.
A delete keeps a copy beside the test folder so undo can put the file back.
"""

import argparse
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from config import TEST_FOLDER
from planner import DUPLICATE_FOLDER, build_plan, summary
from scanner import assert_readable, scan_folder, sha256_file


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
    # A renamed file is only searched in folders this run moved files into.
    destinations = destination_dirs(folder, moves)
    for record in reversed(moves):
        reverse_one(folder, record, destinations)
    # Files are back. Remove only folders this run created, and only when empty.
    remove_created_dirs(folder, created)


def write_record(log_path: Path, record: dict) -> None:
    with Path(log_path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def read_log(log_path: Path) -> list[dict]:
    path = Path(log_path)
    if not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                rows.append(record)
    return rows


def logged_moves(log_path: Path) -> list[dict]:
    return [row for row in read_log(log_path) if row.get("from") and row.get("to")]


def stash_root_for(folder: Path) -> Path:
    # Beside the test folder, so a scan never sees the kept copies.
    return (folder.parent / "undo_deleted").resolve()


def is_deletion(record: dict) -> bool:
    return bool(record.get("deleted") and record.get("stash"))


def unrestored_deletions(log_path) -> list[dict]:
    """Deleted files that still have a kept copy to restore from."""
    folder = Path(TEST_FOLDER).resolve()
    rows = []
    for record in read_log(log_path):
        if is_deletion(record) and (folder.parent / record["stash"]).is_file():
            rows.append(record)
    return rows


def finished_run_ids(log_path: Path) -> set[str]:
    # Older logs marked undone runs instead of dropping their lines.
    done = set()
    for record in read_log(log_path):
        marker = record.get("undo_done")
        if isinstance(marker, str) and marker:
            done.add(marker)
    return done


def drop_records(log_path, unwanted) -> None:
    """Rewrite the log without lines that are finished. An empty log is removed."""
    path = Path(log_path)
    if not path.is_file():
        return
    keep = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                keep.append(text)
                continue
            if isinstance(record, dict) and unwanted(record):
                continue
            keep.append(text)
    if not keep:
        path.unlink()
        return
    temp = path.with_name(path.name + ".tmp")
    temp.write_text("\n".join(keep) + "\n", encoding="utf-8")
    os.replace(temp, path)


def remove_empty_tree(root: Path) -> None:
    if not root.is_dir() or root.is_symlink():
        return
    folders = sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True)
    for path in folders + [root]:
        try:
            path.rmdir()
        except OSError:
            pass


def delete_safe_folder(log_path) -> int | None:
    """Remove the whole Safe to remove folder. Copies are kept so undo can restore it."""
    folder = Path(TEST_FOLDER).resolve()
    assert_readable(folder)
    target = (folder / DUPLICATE_FOLDER).resolve()
    if target.is_symlink() or not target.is_dir() or not stays_inside(folder, target) or target == folder:
        return None
    files = [
        path
        for path in target.rglob("*")
        if path.is_file() and not path.is_symlink() and stays_inside(folder, path)
    ]
    removed = delete_logged(files, log_path) if files else 0
    if files and removed != len(files):
        return removed
    shutil.rmtree(target)
    return removed


def delete_logged(paths, log_path) -> int:
    """Remove files inside the test folder. A copy is kept so undo can restore them."""
    folder = Path(TEST_FOLDER).resolve()
    assert_readable(folder)
    log_path = Path(log_path)
    delete_id = uuid.uuid4().hex
    stash_root = stash_root_for(folder) / delete_id
    removed = 0
    for raw in paths:
        path = Path(raw).resolve()
        if path.is_symlink() or not path.is_file() or not stays_inside(folder, path):
            continue
        rel = path.relative_to(folder).as_posix()
        stash = stash_root / rel
        if not stays_inside(stash_root, stash):
            continue
        stash.parent.mkdir(parents=True, exist_ok=True)
        try:
            digest = sha256_file(path)
            shutil.copy2(path, stash)
            if not stash.is_file() or stash.stat().st_size != path.stat().st_size:
                stash.unlink(missing_ok=True)
                continue
            path.unlink()
        except OSError:
            if stash.exists():
                stash.unlink(missing_ok=True)
            raise
        try:
            write_record(
                log_path,
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "delete_id": delete_id,
                    "deleted": rel,
                    "stash": stash.relative_to(folder.parent).as_posix(),
                    "sha256": digest,
                },
            )
        except OSError:
            shutil.copy2(stash, path)
            stash.unlink(missing_ok=True)
            raise
        removed += 1
    return removed


def restore_deletions(folder: Path, log_path: Path) -> int:
    """Put deleted files back where they were. Then drop the copies and their log lines."""
    stash_root = stash_root_for(folder)
    restored = 0
    for record in reversed(unrestored_deletions(log_path)):
        stash = (folder.parent / record["stash"]).resolve()
        dest = inside_path(folder, record.get("deleted") or "")
        if dest is None or not stays_inside(stash_root, stash):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        target = unique_name(dest)
        if not stays_inside(folder, target):
            continue
        shutil.copy2(stash, target)
        stash.unlink()
        restored += 1
    drop_records(log_path, lambda record: is_deletion(record) or "restored_delete" in record)
    remove_empty_tree(stash_root)
    return restored


def restore_deleted_files(log_path) -> int:
    folder = Path(TEST_FOLDER).resolve()
    assert_readable(folder)
    return restore_deletions(folder, Path(log_path))


def undo_approval(run_id, log_path) -> None:
    """Back to how the folder was before this Approve, deleted files included."""
    folder = Path(TEST_FOLDER).resolve()
    assert_readable(folder)
    log_path = Path(log_path)
    # Deleted copies go back first, so the run below can move them home.
    restore_deletions(folder, log_path)
    if run_id:
        undo(run_id, log_path)
        drop_records(
            log_path,
            lambda record: record.get("run_id") == run_id or record.get("undo_done") == run_id,
        )


def move_one(folder: Path, action: dict, run_id: str, log_path: Path) -> None:
    name = action.get("name") or ""
    destination = action.get("destination") or ""
    current = action.get("folder") or ""
    # Duplicates are already marked with destination _safe_to_remove. Move, never delete.
    if not single_name(name) or not single_name(destination) or (current and not relative_folder(current)):
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
    try:
        digest = sha256_file(src)
    except OSError:
        digest = ""
    src.rename(dest)
    append_log(log_path, run_id, folder, src, dest, digest)


def reverse_one(folder: Path, record: dict, destinations: list[Path]) -> None:
    logged = inside_path(folder, record.get("to") or "")
    dest = inside_path(folder, record.get("from") or "")
    if logged is None or dest is None:
        print("Skipped a move that leaves the test folder.")
        return
    src = logged if logged.is_file() else None
    if src is None:
        # The logged name is gone. The bytes still identify one renamed file.
        src = find_renamed(folder, record.get("sha256") or "", destinations)
        if src is None:
            print(f"Missing, skipped: {record.get('to')}")
            return
        print(f"found renamed: {src.name}")
    dest.parent.mkdir(exist_ok=True)
    target = unique_name(dest)
    if target != dest:
        print(f"Name taken, restored as {target.relative_to(folder).as_posix()}")
    src.rename(target)


def destination_dirs(folder: Path, moves: list[dict]) -> list[Path]:
    found = []
    seen = set()
    for record in moves:
        dest = inside_path(folder, record.get("to") or "")
        if dest is None:
            continue
        directory = dest.parent
        key = str(directory)
        if key in seen:
            continue
        seen.add(key)
        found.append(directory)
    return found


def find_renamed(folder: Path, digest: str, destinations: list[Path]) -> Path | None:
    if not digest:
        return None
    matches = []
    for directory in destinations:
        if directory.is_symlink() or not directory.is_dir():
            continue
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        for item in children:
            if item.is_symlink() or not item.is_file() or not stays_inside(folder, item):
                continue
            try:
                same = sha256_file(item) == digest
            except OSError:
                continue
            if same:
                matches.append(item)
    if len(matches) != 1:
        return None
    return matches[0]


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


def append_log(log_path: Path, run_id: str, folder: Path, src: Path, dest: Path, digest: str) -> None:
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "run_id": run_id,
        "from": src.relative_to(folder).as_posix(),
        "to": dest.relative_to(folder).as_posix(),
        "sha256": digest,
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


def relative_folder(name: str) -> bool:
    """A folder under the chosen one, such as Personal/old. Never .. or a drive path."""
    parts = Path(name).parts
    return bool(parts) and all(single_name(part) for part in parts)


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
    if run_id is None and not unrestored_deletions(log_path):
        print("No runs to undo.")
        return
    undo_approval(run_id, log_path)


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
            # A created folder, or a deleted file, is not a moved file.
            if "from" not in record and ("created_dir" in record or "deleted" in record):
                continue
            counts[run_id] += 1
    return [
        {"run_id": run_id, "timestamp": started[run_id], "count": counts[run_id]}
        for run_id in order
    ]


def latest_run_id(log_path: Path):
    done = finished_run_ids(log_path)
    runs = [run for run in runs_in_log(log_path) if run["count"] and run["run_id"] not in done]
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
        help="Undo the most recent run, and put deleted files back.",
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
