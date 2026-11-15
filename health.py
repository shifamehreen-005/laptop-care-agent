"""Disk space and battery health. This module never touches the user's files."""

import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def disk_status() -> dict:
    """Used and free bytes on C:."""
    usage = shutil.disk_usage("C:\\")
    return {"used": usage.used, "free": usage.free, "total": usage.total}


def battery_health() -> int | None:
    """Full charge as a percent of design capacity. None when there is no battery."""
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as handle:
        report = Path(handle.name)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["powercfg", "/batteryreport", "/xml", "/output", str(report)],
            capture_output=True,
            timeout=60,
            check=False,
            creationflags=flags,
        )
        if result.returncode != 0 or not report.is_file() or report.stat().st_size == 0:
            return None
        root = ET.fromstring(read_report(report))
    except (OSError, subprocess.SubprocessError, ET.ParseError, ValueError):
        return None
    finally:
        # The report is a temp file this function just created.
        report.unlink(missing_ok=True)
    return percent_from_report(root)


def read_report(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8")
    return text.lstrip("\ufeff")


def percent_from_report(root: ET.Element) -> int | None:
    design = 0
    full = 0
    for battery in root.iter():
        # powercfg puts these tags in a namespace, so the local name is what matters.
        if local_name(battery.tag) != "Battery":
            continue
        design_text = child_text(battery, "DesignCapacity")
        full_text = child_text(battery, "FullChargeCapacity")
        if not design_text or not full_text:
            continue
        try:
            design += int(design_text)
            full += int(full_text)
        except ValueError:
            continue
    if design <= 0:
        return None
    return round(full / design * 100)


def child_text(node: ET.Element, tag: str) -> str:
    for child in list(node):
        if local_name(child.tag) == tag and child.text:
            return child.text.strip()
    return ""


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag
