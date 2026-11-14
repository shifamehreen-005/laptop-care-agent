"""Remember a folder's files and folders so a later snapshot can be checked against it."""

from pathlib import Path

from scanner import assert_readable, sha256_file


def snapshot(folder) -> set[tuple[str, str]]:
    """Each file as (relative path, sha256). Each folder as (relative path, "")."""
    root = Path(folder).resolve()
    assert_readable(root)
    found = set()
    for path in root.rglob("*"):
        # A link could point at a real user folder. Stay inside this one.
        if path.is_symlink():
            continue
        if root not in path.resolve().parents:
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            found.add((relative, ""))
            continue
        if path.is_file():
            found.add((relative, sha256_file(path)))
    return found


def compare(before, after) -> list[str]:
    """Lines for entries that are not in both snapshots. Empty means they match."""
    lines = []
    for rel, _digest in sorted(before - after):
        lines.append(f"only in first snapshot: {rel}")
    for rel, _digest in sorted(after - before):
        lines.append(f"only in second snapshot: {rel}")
    return lines
