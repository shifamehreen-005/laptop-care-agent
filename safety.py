"""Say whether a folder may be scanned.

Drive roots and system locations are refused. Ordinary folders are allowed.
"""

import os
from pathlib import Path

# Scanning the source tree would tidy the project itself.
PROJECT_FOLDER = Path(__file__).resolve().parent

BLOCKED_TREES = (
    (Path(r"C:\Windows"), "Windows system folders can't be scanned."),
    (Path(r"C:\Program Files"), "Program folders can't be scanned."),
    (Path(r"C:\Program Files (x86)"), "Program folders can't be scanned."),
    (Path(r"C:\ProgramData"), "Program data can't be scanned."),
)


def is_allowed_folder(path) -> tuple[bool, str]:
    """Return (True, "") or (False, reason). The reason is safe to show."""
    if path is None or not str(path).strip():
        return False, "Choose a folder first."
    try:
        folder = Path(path).expanduser().resolve()
        if not folder.exists():
            return False, "That folder isn't there."
        if not folder.is_dir():
            return False, "That path isn't a folder."
    except OSError:
        return False, "That folder can't be opened."
    if folder == Path(folder.anchor):
        return False, "Choose a folder inside a drive, not the drive itself."
    for root, reason in BLOCKED_TREES:
        if _inside(folder, root):
            return False, reason
    if any(part.lower() == "appdata" for part in folder.parts):
        return False, "App data folders can't be scanned."
    try:
        home = Path.home().resolve()
    except OSError:
        home = None
    if home is not None and folder == home:
        return False, "Choose a folder inside your user folder, not the user folder itself."
    if _is_onedrive_root(folder):
        return False, "Choose a folder inside OneDrive, not the OneDrive folder itself."
    if _inside(folder, PROJECT_FOLDER):
        return False, "The project folder can't be scanned."
    return True, ""


def _inside(folder: Path, root: Path) -> bool:
    try:
        base = root.resolve()
    except OSError:
        return False
    return folder == base or base in folder.parents


def _is_onedrive_root(folder: Path) -> bool:
    for root in _onedrive_roots():
        try:
            if folder == root.resolve():
                return True
        except OSError:
            continue
    return False


def _onedrive_roots() -> list[Path]:
    found = []
    for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        value = os.environ.get(key)
        if value:
            found.append(Path(value))
    home = Path.home()
    found.append(home / "OneDrive")
    try:
        found.extend(path for path in home.glob("OneDrive*") if path.is_dir())
    except OSError:
        pass
    return found
