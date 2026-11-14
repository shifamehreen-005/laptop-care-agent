"""Apply a plan, undo it, and check the folder matches the first snapshot."""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import classifier
import executor
from planner import build_plan, summary
from scanner import scan_folder
from verify import compare, snapshot


def test_undo_restores_snapshot(tmp_path):
    folder = Path(tmp_path) / "Downloads"
    folder.mkdir()
    (folder / "essay.txt").write_text("a school essay about rivers", encoding="utf-8")
    (folder / "copy.txt").write_text("exact duplicate bytes", encoding="utf-8")
    (folder / "notes.txt").write_text("notes that need a free name", encoding="utf-8")
    work = folder / "Work"
    work.mkdir()
    (work / "notes.txt").write_text("already in Work", encoding="utf-8")
    (work / "notes (2).txt").write_text("the second name is taken too", encoding="utf-8")

    executor.TEST_FOLDER = str(folder)
    before = snapshot(folder)
    log_path = Path(tmp_path) / "undo.log"
    plan = [
        {"name": "essay.txt", "destination": "School"},
        {"name": "copy.txt", "destination": "_safe_to_remove"},
        {"name": "notes.txt", "destination": "Work"},
    ]

    assert executor.apply_plan(plan, False, log_path) is None
    assert snapshot(folder) == before
    assert not log_path.exists()

    run_id = executor.apply_plan(plan, True, log_path)
    moved = snapshot(folder)
    assert ("School/essay.txt", file_hash(before, "essay.txt")) in moved
    assert ("_safe_to_remove/copy.txt", file_hash(before, "copy.txt")) in moved
    assert ("Work/notes (3).txt", file_hash(before, "notes.txt")) in moved
    assert not any(path == "essay.txt" for path, _digest in moved)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    logged = [json.loads(line) for line in lines]
    moves = [item for item in logged if "from" in item]
    created = [item for item in logged if "created_dir" in item]
    assert len(moves) == 3
    assert [item["run_id"] for item in moves] == [run_id, run_id, run_id]
    assert moves[0]["from"] == "essay.txt" and moves[0]["to"] == "School/essay.txt"
    assert moves[2]["to"] == "Work/notes (3).txt"
    assert set(moves[0]) == {"timestamp", "run_id", "from", "to"}
    assert {item["created_dir"] for item in created} == {"School", "_safe_to_remove"}
    assert all(set(item) == {"run_id", "created_dir"} and item["run_id"] == run_id for item in created)

    executor.undo(run_id, log_path)
    after = snapshot(folder)
    assert after == before, "\n".join(compare(before, after))


def test_undo_skips_a_missing_file_and_continues(tmp_path):
    folder = Path(tmp_path) / "Downloads"
    folder.mkdir()
    (folder / "School").mkdir()
    (folder / "School" / "kept.txt").write_text("still here", encoding="utf-8")
    executor.TEST_FOLDER = str(folder)
    log_path = Path(tmp_path) / "undo.log"
    run_id = "run-missing"
    records = [
        {
            "timestamp": "2026-11-13T12:00:01",
            "run_id": run_id,
            "from": "kept.txt",
            "to": "School/kept.txt",
        },
        {
            "timestamp": "2026-11-13T12:00:02",
            "run_id": run_id,
            "from": "gone.txt",
            "to": "School/gone.txt",
        },
    ]
    # Newer line last, so undo tries the missing file first and must continue.
    log_path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    executor.undo(run_id, log_path)
    assert (folder / "kept.txt").is_file()
    assert not (folder / "School" / "gone.txt").exists()


def test_oldest_plain_name_is_kept(tmp_path):
    folder = Path(tmp_path) / "Downloads"
    folder.mkdir()
    receipts = folder / "Receipts"
    receipts.mkdir()
    # Added Jan 2, even though it was edited later. Alphabetically it would lose to invoice.txt.
    older = receipts / "inovice_march.txt"
    newer = folder / "invoice.txt"
    older.write_text("same receipt bytes", encoding="utf-8")
    newer.write_text("same receipt bytes", encoding="utf-8")
    set_times(older, added=1_704_182_400, modified=1_800_000_000)
    set_times(newer, added=1_704_268_800, modified=1_600_000_000)
    # Copy-style, and older than both plain names. It still loses.
    copy = folder / "invoice (1).txt"
    copy.write_text("same receipt bytes", encoding="utf-8")
    set_times(copy, added=1_600_000_000, modified=1_600_000_000)

    # Same arrival: the older edit wins. Names would pick report_b first.
    early_edit = folder / "report_b.txt"
    late_edit = folder / "report_a.txt"
    early_edit.write_text("same report bytes", encoding="utf-8")
    late_edit.write_text("same report bytes", encoding="utf-8")
    set_times(early_edit, added=1_700_000_000, modified=1_700_000_000)
    set_times(late_edit, added=1_700_000_000, modified=1_700_086_400)

    # Same arrival and same edit: alphabetical name wins.
    first = folder / "alpha.txt"
    second = folder / "mid.txt"
    first.write_text("same alpha bytes", encoding="utf-8")
    second.write_text("same alpha bytes", encoding="utf-8")
    set_times(first, added=1_710_000_000, modified=1_710_000_000)
    set_times(second, added=1_710_000_000, modified=1_710_000_000)

    records = {item["name"]: item for item in scan_folder(folder)}
    assert records["inovice_march.txt"]["is_duplicate"] is False
    assert records["inovice_march.txt"]["folder"] == "Receipts"
    assert records["invoice.txt"]["is_duplicate"] is True
    assert records["invoice.txt"]["duplicate_of"] == "inovice_march.txt"
    assert records["invoice (1).txt"]["duplicate_of"] == "inovice_march.txt"
    assert records["report_b.txt"]["is_duplicate"] is False
    assert records["report_a.txt"]["duplicate_of"] == "report_b.txt"
    assert records["alpha.txt"]["is_duplicate"] is False
    assert records["mid.txt"]["duplicate_of"] == "alpha.txt"


def test_duplicate_inside_category_folder(tmp_path):
    folder = Path(tmp_path) / "Downloads"
    folder.mkdir()
    receipts = folder / "Receipts"
    receipts.mkdir()
    (receipts / "invoice.txt").write_text("same receipt bytes", encoding="utf-8")
    (receipts / "invoice (1).txt").write_text("same receipt bytes", encoding="utf-8")
    # The user made this folder. Its file is not part of the scan.
    personal = folder / "Personal"
    personal.mkdir()
    (personal / "invoice (2).txt").write_text("same receipt bytes", encoding="utf-8")

    executor.TEST_FOLDER = str(folder)
    files = scan_folder(folder)
    assert {item["name"] for item in files} == {"invoice.txt", "invoice (1).txt"}
    plan = build_plan(files, use_ai=False)
    assert plan == [
        {
            "name": "invoice (1).txt",
            "folder": "Receipts",
            "destination": "_safe_to_remove",
            "reason": "copy of invoice.txt",
            "source": "rule",
        }
    ]
    before = snapshot(folder)
    log_path = Path(tmp_path) / "undo.log"
    run_id = executor.apply_plan(plan, True, log_path)
    assert (folder / "_safe_to_remove" / "invoice (1).txt").is_file()
    assert not (folder / "Receipts" / "invoice (1).txt").exists()
    assert (personal / "invoice (2).txt").is_file()
    executor.undo(run_id, log_path)
    after = snapshot(folder)
    assert after == before, "\n".join(compare(before, after))


def test_suggested_fix_applied_and_undone(tmp_path):
    folder = Path(tmp_path) / "Downloads"
    folder.mkdir()
    work = folder / "Work"
    work.mkdir()
    (work / "invoice.txt").write_text("paid the gym", encoding="utf-8")
    (work / "meeting.txt").write_text("meeting notes for monday", encoding="utf-8")
    (work / "random.txt").write_text("nothing special in this note at all", encoding="utf-8")

    executor.TEST_FOLDER = str(folder)

    def refuse_ai(*_args, **_kwargs):
        raise AssertionError("AI was asked about a file that already has a folder")

    original_ask = classifier.ask_model
    classifier.ask_model = refuse_ai
    try:
        files = scan_folder(folder)
        plan = build_plan(files, use_ai=True)
    finally:
        classifier.ask_model = original_ask
    assert plan == [
        {
            "name": "invoice.txt",
            "folder": "Work",
            "destination": "Receipts",
            "reason": "invoice.txt is in Work but looks like Receipts",
            "source": "rule",
            "suggested": True,
        }
    ]
    assert summary(plan) == "invoice.txt is in Work but looks like Receipts"

    before = snapshot(folder)
    log_path = Path(tmp_path) / "undo.log"
    prompts = []
    answers = iter(["no", "no"])

    def fake_input(prompt):
        prompts.append(prompt)
        return next(answers)

    executor.input = fake_input
    try:
        executor.command_apply(log_path)
    finally:
        del executor.input
    assert prompts == [
        "Type yes to continue: ",
        "Also apply 1 suggested fixes? (yes/no): ",
    ]
    assert snapshot(folder) == before

    run_id = executor.apply_plan(plan, False, log_path, suggestions=True)
    assert (folder / "Receipts" / "invoice.txt").is_file()
    assert not (work / "invoice.txt").exists()
    logged = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    moves = [item for item in logged if "from" in item]
    assert moves[0]["from"] == "Work/invoice.txt"
    assert moves[0]["to"] == "Receipts/invoice.txt"
    executor.undo(run_id, log_path)
    after = snapshot(folder)
    assert after == before, "\n".join(compare(before, after))
    assert (work / "invoice.txt").is_file()


def set_times(path: Path, added: int, modified: int) -> None:
    """Set creation time (added) and modified time. Creation time is st_birthtime on Windows."""
    os.utime(path, (modified, modified))
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.SetFileTime.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel32.SetFileTime.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateFileW(str(path), 0x0100, 7, None, 3, 0x80, None)
    invalid = ctypes.c_void_p(-1).value
    if handle is None or handle == invalid or handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), "CreateFileW")
    try:
        ticks = int((added + 11644473600) * 10_000_000)
        created = wintypes.FILETIME(ticks & 0xFFFFFFFF, (ticks >> 32) & 0xFFFFFFFF)
        if not kernel32.SetFileTime(handle, ctypes.byref(created), None, None):
            raise OSError(ctypes.get_last_error(), "SetFileTime")
    finally:
        kernel32.CloseHandle(handle)


def file_hash(snap, relative: str) -> str:
    for path, digest in snap:
        if path == relative:
            return digest
    raise AssertionError(relative)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="laptop-care-undo-") as directory:
        test_undo_restores_snapshot(directory)
    with tempfile.TemporaryDirectory(prefix="laptop-care-undo-") as directory:
        test_undo_skips_a_missing_file_and_continues(directory)
    with tempfile.TemporaryDirectory(prefix="laptop-care-undo-") as directory:
        test_oldest_plain_name_is_kept(directory)
    with tempfile.TemporaryDirectory(prefix="laptop-care-undo-") as directory:
        test_duplicate_inside_category_folder(directory)
    with tempfile.TemporaryDirectory(prefix="laptop-care-undo-") as directory:
        test_suggested_fix_applied_and_undone(directory)
    print("ok")
