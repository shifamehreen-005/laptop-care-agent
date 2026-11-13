"""Fill TEST_FOLDER with a messy, labeled set of sample downloads.

Usage:
    python make_test_folder.py
    python make_test_folder.py --count 120 --seed 42
"""

import argparse
import csv
import os
import random
import shutil
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

from config import CATEGORIES, TEST_FOLDER

# Shares of the whole batch. They sum to 100 so any --count keeps this mix.
# 8 means 4 copies in 50 files and 10 copies in 120.
MIX = (
    ("Receipts", 16),
    ("School", 12),
    ("Work", 12),
    ("Screenshots", 14),
    ("Installers", 12),
    ("Archives", 8),
    ("Photos", 12),
    ("Other", 6),
    ("duplicates", 8),
)

RECEIPT_NAMES = [
    "invoice.pdf",
    "Receipt_Amazon.pdf",
    "uber_receipt.pdf",
    "electric_bill.pdf",
    "Invoice_1042.pdf",
    "starbucks_receipt.pdf",
    "internet_bill.pdf",
    "order_confirmation.pdf",
]
SCHOOL_NAMES = [
    "biology_notes.docx",
    "history_homework.docx",
    "algebra_homework.docx",
    "english_essay.docx",
    "chemistry_lab.docx",
    "spanish_vocab.docx",
]
WORK_NAMES = [
    "status_update.docx",
    "meeting_notes.docx",
    "project_brief.docx",
    "client_review.docx",
    "weekly_plan.docx",
    "team_agenda.docx",
]
# Filename does not say the category. The paragraph text does.
VAGUE_NAMES = [
    "final_v2_REAL.docx",
    "Document.docx",
    "notes_final.docx",
    "copy.docx",
    "Untitled.docx",
    "draft.docx",
    "New Microsoft Word Document.docx",
    "stuff.docx",
    "FINAL.docx",
    "important.docx",
]
EXE_NAMES = [
    "ChromeSetup.exe",
    "python-3.12.8-amd64.exe",
    "VSCodeUserSetup.exe",
    "SpotifySetup.exe",
]
MSI_NAMES = [
    "7z2408-x64.msi",
    "Git-2.47.0-64-bit.msi",
    "node-v20.18.0-x64.msi",
]
ARCHIVE_NAMES = [
    "photos_backup.zip",
    "old_files.zip",
    "backup.zip",
    "bundle.zip",
]
OTHER_NAMES = [
    "New Text Document.txt",
    "export.csv",
    "scratch.txt",
    "temp_export.csv",
    "download.txt",
]
VENDORS = [
    "Northwind Supply",
    "City Power",
    "Harbor Transit",
    "Cafe Luna",
    "Summit Software",
]
COURSES = ["Biology 101", "World History", "Algebra II", "English Literature"]
PROJECTS = ["website refresh", "client onboarding", "budget review", "support queue"]


class Planned(NamedTuple):
    name: str
    category: str
    when: datetime
    source: str | None = None


def die(message: str) -> None:
    sys.exit(message)


def allocate(count: int) -> dict[str, int]:
    """Split count by MIX. Largest remainders get the leftover files."""
    exact = [count * weight / 100 for _, weight in MIX]
    counts = [int(value) for value in exact]
    leftover = count - sum(counts)
    order = sorted(
        range(len(MIX)),
        key=lambda index: (-(exact[index] - counts[index]), index),
    )
    for index in order[:leftover]:
        counts[index] += 1
    return {name: counts[index] for index, (name, _) in enumerate(MIX)}


def assert_sandbox(folder: Path) -> None:
    # A joined path or a link must not land in the real user folders.
    if not folder.is_absolute():
        die("TEST_FOLDER must be an absolute path.")
    candidate = folder.resolve()
    home = Path.home()
    blocked = [home / name for name in ("Downloads", "Desktop", "Documents")]
    blocked.extend(home.glob("OneDrive*/Downloads"))
    blocked.extend(home.glob("OneDrive*/Desktop"))
    blocked.extend(home.glob("OneDrive*/Documents"))
    for root in blocked:
        root = root.resolve()
        if candidate == root or root in candidate.parents:
            die(
                f"Refusing to touch {candidate}. "
                "Only the test folder is allowed, never real Downloads, Desktop, or Documents."
            )


def assert_can_fill(folder: Path, labels_path: Path) -> None:
    if folder.exists() and not folder.is_dir():
        die(f"Refusing to run. {folder} is not a folder.")
    # A second run would mix new files into a set we already labeled.
    if folder.is_dir() and any(folder.iterdir()):
        die(f"Refusing to run. {folder} is not empty.")
    # labels.csv is the answer key. Never overwrite it.
    if labels_path.exists():
        die(f"Refusing to run. {labels_path} already exists.")


def two_years_ago(now: datetime) -> datetime:
    try:
        return now.replace(year=now.year - 2)
    except ValueError:
        return now.replace(year=now.year - 2, day=28)


def make_dates(count: int, rng: random.Random) -> list[datetime]:
    # Fixed clock so the same --seed rebuilds the same timestamps, not a new set each day.
    # Even slots across two years, then shuffle, so dates are not grouped by type.
    now = datetime(2026, 11, 13, 12, 0, 0)
    start = two_years_ago(now)
    span = (now - start).total_seconds()
    half_slot = span / (count * 2)
    dates = []
    for index in range(count):
        base = span * (index + 0.5) / count
        offset = min(span, max(0, base + rng.uniform(-half_slot, half_slot)))
        dates.append(start + timedelta(seconds=offset))
    rng.shuffle(dates)
    return dates


def claim(used: set[str], name: str) -> str:
    """Keep a name, or add _2, _3, ... (1) is reserved for exact copies."""
    if name not in used:
        used.add(name)
        return name
    path = Path(name)
    number = 2
    while True:
        candidate = f"{path.stem}_{number}{path.suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        number += 1


def typo_plans(rng: random.Random, plans: list[Planned]) -> list[Planned]:
    # inovice_march.pdf is a renamed copy of invoice.pdf, dated later so the original name is kept.
    invoice = next((item for item in plans if item.name == "invoice.pdf"), None)
    if invoice is None:
        die("invoice.pdf is missing, so inovice_march.pdf cannot be a copy of it.")
    now = datetime(2026, 11, 13, 12, 0, 0)
    start = two_years_ago(now)
    span = (now - start).total_seconds()
    homework_when = start + timedelta(seconds=rng.uniform(0, span))
    return [
        Planned("inovice_march.pdf", "Receipts", invoice.when + timedelta(days=1), "invoice.pdf"),
        Planned("homewrok.docx", "School", homework_when),
    ]


# Names and wording skip the rule keywords. The meaning still fits the category.
HARD_FILES = (
    (
        "Document (3).docx",
        "School",
        "History essay\n"
        "\n"
        "Rome did not fall in a single day. Trade slowed, the army split, "
        "and local leaders took charge of the towns.\n"
        "Weak roads and empty farms mattered more than one battle. "
        "This draft is for the Friday class.\n",
    ),
    (
        "scan_0042.pdf",
        "Other",
        "LEASE SUMMARY\n"
        "Unit 4B, 18 Oak Street\n"
        "Tenant: Sam Rivera\n"
        "Rent: 1450 each month\n"
        "Term: 1 August 2025 to 31 July 2026\n"
        "Deposit: 1450, due before move-in\n"
        "Keep the unit clean and pay rent on the first day.\n",
    ),
    (
        "doc1.docx",
        "Work",
        "Dear hiring team,\n"
        "\n"
        "I am applying for the junior analyst role at Harbor Transit. "
        "I have two years of spreadsheet work and I like clear writing.\n"
        "I can start in June. Thank you for reading this letter.\n",
    ),
    (
        "payment_aug.pdf",
        "Receipts",
        "PAYMENT\n"
        "Number: PAY-2208\n"
        "Date: August 14, 2025\n"
        "From: City Gym\n"
        "Bill to: Sam Rivera\n"
        "\n"
        "August membership 39.00\n"
        "Tax 3.12\n"
        "Total paid 42.12\n"
        "\n"
        "Card ending 4242. Paid in full.\n",
    ),
    (
        "reading.docx",
        "School",
        "Reading summary\n"
        "\n"
        "Chapter 2 of The Warming Earth explains how ice cores store old air. "
        "The writer compares two cores from Greenland and Antarctica.\n"
        "Main idea: trapped bubbles show that warm years came after high gas levels. "
        "I will use this chapter in the Friday essay.\n",
    ),
)
HARD_TEXT = {name: text for name, _category, text in HARD_FILES}


def hard_plans(rng: random.Random) -> list[Planned]:
    now = datetime(2026, 11, 13, 12, 0, 0)
    start = two_years_ago(now)
    span = (now - start).total_seconds()
    plans = []
    for name, category, _text in HARD_FILES:
        when = start + timedelta(seconds=rng.uniform(0, span))
        plans.append(Planned(name, category, when))
    return plans


def copy_name(name: str, number: int) -> str:
    path = Path(name)
    return f"{path.stem} ({number}){path.suffix}"


def pick_name(used: set[str], options: list[str], index: int, fallback: str) -> str:
    name = options[index] if index < len(options) else fallback.format(n=index + 1)
    return claim(used, name)


def screenshot_name(when: datetime, used: set[str]) -> tuple[str, datetime]:
    candidate = when.replace(microsecond=0)
    while True:
        name = candidate.strftime("Screenshot %Y-%m-%d %H%M%S.png")
        if name not in used:
            used.add(name)
            return name, candidate
        candidate += timedelta(seconds=1)


def build_plans(counts: dict[str, int], dates: list[datetime]) -> list[Planned]:
    used: set[str] = set()
    vague_at = 0
    coming = iter(dates)
    unique: list[Planned] = []

    def take_date() -> datetime:
        return next(coming)

    def add(name: str, category: str, when: datetime | None = None) -> None:
        unique.append(Planned(name, category, when or take_date()))

    for index in range(counts["Receipts"]):
        add(pick_name(used, RECEIPT_NAMES, index, "Invoice_{n}.pdf"), "Receipts")

    for index in range(counts["School"]):
        when = take_date()
        if index % 3 == 0:
            name = claim(used, VAGUE_NAMES[vague_at % len(VAGUE_NAMES)])
            vague_at += 1
        else:
            name = pick_name(used, SCHOOL_NAMES, index, "class_notes_{n}.docx")
        add(name, "School", when)

    for index in range(counts["Work"]):
        when = take_date()
        if index % 3 == 0:
            name = claim(used, VAGUE_NAMES[vague_at % len(VAGUE_NAMES)])
            vague_at += 1
        else:
            name = pick_name(used, WORK_NAMES, index, "work_notes_{n}.docx")
        add(name, "Work", when)

    for _ in range(counts["Screenshots"]):
        when = take_date()
        name, when = screenshot_name(when, used)
        add(name, "Screenshots", when)

    for index in range(counts["Installers"]):
        # Alternate so a batch always has both .exe and .msi when it has 2 or more.
        if index % 2 == 0:
            name = pick_name(used, EXE_NAMES, index // 2, "Setup_{n}.exe")
        else:
            name = pick_name(used, MSI_NAMES, index // 2, "Package_{n}.msi")
        add(name, "Installers")

    for index in range(counts["Archives"]):
        add(pick_name(used, ARCHIVE_NAMES, index, "archive_{n}.zip"), "Archives")

    for index in range(counts["Photos"]):
        add(claim(used, f"IMG_{4821 + index * 13}.jpg"), "Photos")

    for index in range(counts["Other"]):
        add(pick_name(used, OTHER_NAMES, index, "leftover_{n}.txt"), "Other")

    copies = choose_copies(unique, counts["duplicates"])
    plans = list(unique)
    seen: dict[str, int] = {}
    for source in copies:
        seen[source.name] = seen.get(source.name, 0) + 1
        name = claim(used, copy_name(source.name, seen[source.name]))
        plans.append(Planned(name, source.category, take_date(), source.name))
    return plans


def choose_copies(unique: list[Planned], how_many: int) -> list[Planned]:
    """Take one file from each category, receipts first, so copies are spread out."""
    pools: dict[str, list[Planned]] = {name: [] for name, _ in MIX if name != "duplicates"}
    for item in unique:
        pools[item.category].append(item)
    receipts = pools["Receipts"]
    receipts.sort(key=lambda item: item.name.lower() != "invoice.pdf")

    picks: list[Planned] = []
    while len(picks) < how_many and any(pools.values()):
        for name, _ in MIX:
            if name == "duplicates" or not pools[name]:
                continue
            picks.append(pools[name].pop(0))
            if len(picks) == how_many:
                break
    if not picks:
        return []
    index = 0
    originals = list(picks)
    while len(picks) < how_many:
        picks.append(originals[index % len(originals)])
        index += 1
    return picks


def inside_folder(folder: Path, name: str) -> Path:
    path = (folder / name).resolve()
    if path.parent != folder.resolve():
        die(f"Refusing to write outside the test folder: {name}")
    if path.exists():
        die(f"Refusing to overwrite {path}")
    return path


def stamp(path: Path, when: datetime) -> None:
    timestamp = when.timestamp()
    os.utime(path, (timestamp, timestamp))


def write_pdf(path: Path, text: str) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 8, text)
    pdf.output(str(path))


def write_docx(path: Path, text: str) -> None:
    from docx import Document

    document = Document()
    for line in text.split("\n"):
        document.add_paragraph(line)
    document.save(str(path))


SCREEN_SIZES = ((1280, 720), (1920, 1080), (800, 600))
WINDOW_KINDS = ("browser", "chat", "sheet", "error", "code")
PHOTO_SIZES = ((800, 600), (1024, 768), (640, 480), (960, 720), (768, 1024))
BROWSER_LINES = (
    "Milk, bread, and tea.",
    "Pickup is after class.",
    "Saved a copy locally.",
    "Reply before Friday.",
    "See the attached note.",
    "Open the next page.",
)
CHAT_LINES = (
    "On my way",
    "Got it",
    "See you at noon",
    "Can you resend?",
    "Sounds good",
    "One minute",
)
CODE_SNIPPETS = (
    ("total = count + 1", "if ready:", "    save(name)", "return total"),
    ("name = 'notes'", "for item in files:", "    print(item)", "done = True"),
    ("done = True", "if ready:", "    save(name)", "return total"),
)
ERROR_TITLES = ("Can't open this file", "Something went wrong", "Action needed")
ERROR_LINES = (
    "This file is already open.",
    "Try again in a moment.",
    "The name was not found.",
)
SHEET_VALUES = ("12", "4", "18", "OK", "3", "9", "Yes")


def ui_font(size: int, mono: bool = False):
    # The built-in font stays tiny on a full-size capture, so use a real UI font.
    from PIL import ImageFont

    filename = "consola.ttf" if mono else "segoeui.ttf"
    try:
        return ImageFont.truetype(rf"C:\Windows\Fonts\{filename}", size)
    except OSError:
        return ImageFont.load_default(size)


def picture_rng(seed: int, kind: str, key: str) -> random.Random:
    # Tied to --seed so the same seed redraws the same picture.
    return random.Random(f"{seed}|{kind}|{key}")


def paint_title_bar(draw, width: int, bar_h: int, when: datetime, rng: random.Random) -> None:
    # The clock in the bar makes two similar screens different files.
    color = (rng.randint(20, 55), rng.randint(22, 60), rng.randint(28, 72))
    draw.rectangle((0, 0, width, bar_h), fill=color)
    font = ui_font(max(14, bar_h // 2))
    stamp = when.strftime("%Y-%m-%d %H:%M:%S")
    box = draw.textbbox((0, 0), stamp, font=font)
    text_h = box[3] - box[1]
    draw.text((16, max(0, (bar_h - text_h) // 2)), stamp, fill=(245, 245, 245), font=font)
    for index, dot in enumerate(((240, 90, 80), (240, 190, 70), (80, 190, 90))):
        center = width - 22 - index * 22
        draw.ellipse((center, bar_h // 2 - 6, center + 12, bar_h // 2 + 6), fill=dot)


def text_height(draw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[3] - box[1]


def draw_browser(draw, rng: random.Random, width: int, height: int, top: int, font) -> None:
    page = (rng.randint(236, 250), rng.randint(236, 248), rng.randint(240, 252))
    accent = (rng.randint(20, 70), rng.randint(80, 140), rng.randint(150, 210))
    draw.rectangle((0, top, width, height), fill=page)
    address = rng.choice(("https://notes.local/today", "https://mail.local/inbox", "https://docs.local/page"))
    line_h = text_height(draw, address, font)
    bar_top = top + 16
    addr_h = line_h + 18
    draw.rounded_rectangle(
        (16, bar_top, width - 16, bar_top + addr_h),
        radius=8,
        fill=(255, 255, 255),
        outline=accent,
    )
    draw.text((28, bar_top + 8), address, fill=(50, 50, 50), font=font)
    y = bar_top + addr_h + 18
    draw.text((32, y), rng.choice(("Today", "Inbox", "Notes")), fill=accent, font=font)
    y += line_h + 16
    for line in rng.sample(BROWSER_LINES, k=3):
        draw.text((32, y), line, fill=(40, 40, 45), font=font)
        y += line_h + 12


def draw_chat(draw, rng: random.Random, width: int, height: int, top: int, font) -> None:
    background = (rng.randint(232, 246), rng.randint(234, 246), rng.randint(238, 250))
    side = (rng.randint(36, 72), rng.randint(48, 96), rng.randint(72, 130))
    draw.rectangle((0, top, width, height), fill=background)
    side_w = max(140, width // 4)
    draw.rectangle((0, top, side_w, height), fill=side)
    y = top + 18
    for name in rng.sample(("Alex", "Jordan", "Sam", "Riley", "Casey"), k=3):
        draw.text((16, y), name, fill=(240, 244, 248), font=font)
        y += 46
    y = top + 22
    line_h = text_height(draw, "On my way", font)
    bubble_h = line_h + 20
    for index, line in enumerate(rng.sample(CHAT_LINES, k=4)):
        mine = index % 2 == 1
        bubble_w = min(420, max(220, width // 3))
        left = width - bubble_w - 28 if mine else side_w + 20
        fill = (186, 214, 186) if mine else (255, 255, 255)
        draw.rounded_rectangle((left, y, left + bubble_w, y + bubble_h), radius=12, fill=fill)
        draw.text((left + 14, y + 8), line, fill=(30, 30, 30), font=font)
        y += bubble_h + 16


def draw_sheet(draw, rng: random.Random, width: int, height: int, top: int, font) -> None:
    draw.rectangle((0, top, width, height), fill=(252, 252, 252))
    header = (rng.randint(186, 220), rng.randint(206, 232), rng.randint(176, 214))
    cols, rows = 6, 8
    left, grid_top = 56, top + 8
    col_w = (width - left - 8) // cols
    row_h = (height - grid_top - 8) // rows
    draw.rectangle((left, grid_top, left + cols * col_w, grid_top + row_h), fill=header)
    for col in range(cols):
        draw.text((left + col * col_w + 8, grid_top + 8), chr(ord("A") + col), fill=(40, 40, 40), font=font)
    for row in range(rows):
        y = grid_top + row * row_h
        draw.line((left, y, left + cols * col_w, y), fill=(190, 190, 190))
        if row:
            draw.text((12, y + 8), str(row), fill=(90, 90, 90), font=font)
    for col in range(cols + 1):
        x = left + col * col_w
        draw.line((x, grid_top, x, grid_top + rows * row_h), fill=(190, 190, 190))
    for _ in range(rng.randint(4, 7)):
        col = rng.randint(0, cols - 1)
        row = rng.randint(1, rows - 1)
        draw.text(
            (left + col * col_w + 8, grid_top + row * row_h + 8),
            rng.choice(SHEET_VALUES),
            fill=(25, 25, 25),
            font=font,
        )


def draw_error(draw, rng: random.Random, width: int, height: int, top: int, font) -> None:
    desktop = (rng.randint(150, 190), rng.randint(165, 205), rng.randint(175, 215))
    draw.rectangle((0, top, width, height), fill=desktop)
    box_w = min(width - 80, max(420, width // 2))
    box_h = min(height - top - 60, max(200, height // 3))
    x = (width - box_w) // 2
    y = top + (height - top - box_h) // 2
    draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=8, fill=(250, 250, 250))
    draw.ellipse((x + 28, y + 32, x + 68, y + 72), fill=(196, 52, 46))
    draw.text((x + 84, y + 40), rng.choice(ERROR_TITLES), fill=(130, 36, 32), font=font)
    draw.text((x + 28, y + 100), rng.choice(ERROR_LINES), fill=(40, 40, 40), font=font)
    button = (x + box_w - 110, y + box_h - 52, x + box_w - 24, y + box_h - 18)
    draw.rounded_rectangle(button, radius=6, fill=(48, 102, 176))
    draw.text((button[0] + 30, button[1] + 6), "OK", fill=(255, 255, 255), font=font)


def draw_code(draw, rng: random.Random, width: int, height: int, top: int, font) -> None:
    background = (rng.randint(24, 42), rng.randint(26, 44), rng.randint(34, 56))
    tab = (rng.randint(48, 78), rng.randint(58, 96), rng.randint(78, 130))
    draw.rectangle((0, top, width, height), fill=background)
    draw.rectangle((0, top, 150, top + 34), fill=tab)
    draw.text((12, top + 8), rng.choice(("notes.py", "main.py", "app.js")), fill=(230, 230, 230), font=font)
    y = top + 52
    step = max(28, height // 18)
    for number, line in enumerate(rng.choice(CODE_SNIPPETS), start=1):
        draw.text((12, y), str(number), fill=(120, 128, 150), font=font)
        ink = rng.choice(((170, 214, 176), (214, 196, 140), (150, 186, 224), (224, 170, 170)))
        draw.text((48, y), line, fill=ink, font=font)
        y += step


def write_screenshot(path: Path, when: datetime, seed: int) -> None:
    from PIL import Image, ImageDraw

    stamp = when.strftime("%Y-%m-%d %H:%M:%S")
    rng = picture_rng(seed, "screenshot", stamp)
    width, height = rng.choice(SCREEN_SIZES)
    kind = rng.choice(WINDOW_KINDS)
    image = Image.new("RGB", (width, height), (244, 244, 244))
    draw = ImageDraw.Draw(image)
    bar_h = max(40, height // 14)
    paint_title_bar(draw, width, bar_h, when, rng)
    body = ui_font(max(15, height // 40), mono=(kind == "code"))
    drawer = {
        "browser": draw_browser,
        "chat": draw_chat,
        "sheet": draw_sheet,
        "error": draw_error,
        "code": draw_code,
    }[kind]
    drawer(draw, rng, width, height, bar_h, body)
    image.save(path, "PNG")
    image.close()


def soft_color(rng: random.Random) -> tuple[int, int, int]:
    # Pull each channel toward white so blocks and gradients stay soft.
    return tuple((rng.randint(80, 200) + 255) // 2 for _ in range(3))


def soft_gradient(width: int, height: int, rng: random.Random):
    from PIL import Image

    start = Image.new("RGB", (width, height), soft_color(rng))
    end = Image.new("RGB", (width, height), soft_color(rng))
    # Rotate the square gradient before resizing, or a wide photo gets a mismatched mask.
    mask = Image.linear_gradient("L")
    if rng.random() < 0.5:
        mask = mask.transpose(Image.Transpose.ROTATE_90)
    return Image.composite(end, start, mask.resize((width, height)))


def soft_blocks(width: int, height: int, rng: random.Random):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), soft_color(rng))
    draw = ImageDraw.Draw(image)
    bands = rng.randint(3, 6)
    if rng.random() < 0.5:
        band = height // bands
        for index in range(bands):
            draw.rectangle((0, index * band, width, (index + 1) * band + 1), fill=soft_color(rng))
    else:
        band = width // bands
        for index in range(bands):
            draw.rectangle((index * band, 0, (index + 1) * band + 1, height), fill=soft_color(rng))
    return image


def write_photo(path: Path, index: int, seed: int) -> None:
    from PIL import Image, ImageDraw

    rng = picture_rng(seed, "photo", str(index))
    width, height = rng.choice(PHOTO_SIZES)
    image = soft_gradient(width, height, rng) if rng.random() < 0.5 else soft_blocks(width, height, rng)
    draw = ImageDraw.Draw(image)
    for _ in range(rng.randint(3, 7)):
        x = rng.randint(-width // 10, width)
        y = rng.randint(-height // 10, height)
        box = (
            x,
            y,
            x + rng.randint(width // 10, width // 2),
            y + rng.randint(height // 10, height // 2),
        )
        if rng.random() < 0.5:
            draw.ellipse(box, fill=soft_color(rng))
        else:
            draw.rectangle(box, fill=soft_color(rng))
    image.save(path, "JPEG", quality=75)
    image.close()


def write_installer(path: Path) -> None:
    # Plain text, not a real program, so the file cannot launch.
    message = (
        "Dummy installer for the Laptop Care test folder.\n"
        "This file is not a real program.\n"
        f"Name: {path.name}\n"
    )
    path.write_bytes(message.encode("ascii"))


def write_archive(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "readme.txt",
            f"Packed file: {path.name}\nOld files kept together.\n",
        )


def write_other(path: Path, index: int) -> None:
    if path.suffix.lower() == ".csv":
        path.write_text(
            "left_col,right_col\n"
            f"{index + 1},saved\n"
            f"{index + 2},later\n",
            encoding="utf-8",
        )
        return
    path.write_text(
        f"Leftover download {index + 1}\n"
        "Saved this and forgot what it was for.\n",
        encoding="utf-8",
    )


def receipt_text(name: str, index: int, when: datetime) -> str:
    lowered = name.lower()
    if "bill" in lowered:
        kind = "BILL"
    elif "invoice" in lowered:
        kind = "INVOICE"
    else:
        kind = "RECEIPT"
    amount = round(12.5 + index * 7.35, 2)
    tax = round(amount * 0.08, 2)
    total = round(amount + tax, 2)
    return (
        f"{kind}\n"
        f"Number: INV-{1400 + index}\n"
        f"Date: {when.strftime('%B %d, %Y')}\n"
        f"From: {VENDORS[index % len(VENDORS)]}\n"
        f"Bill to: Sam Rivera\n"
        f"\n"
        f"Description: Office supplies order {index + 1}\n"
        f"Amount: {amount:.2f}\n"
        f"Tax: {tax:.2f}\n"
        f"Total due: {total:.2f}\n"
        f"\n"
        f"Paid in full. Keep this receipt for your records.\n"
    )


def school_text(index: int) -> str:
    course = COURSES[index % len(COURSES)]
    return (
        f"{course} lecture notes\n"
        f"\n"
        f"Class meeting {index + 1}. The homework is due next Friday.\n"
        f"Read the textbook chapter and answer the quiz review questions.\n"
        f"Essay outline: introduction, two examples, and a short conclusion.\n"
        f"I still need to study the vocabulary list before the exam.\n"
    )


def work_text(index: int) -> str:
    project = PROJECTS[index % len(PROJECTS)]
    return (
        f"Work notes for the {project}\n"
        f"\n"
        f"Status update {index + 1} for the team meeting.\n"
        f"The client asked for a Friday review. The deadline is next Wednesday.\n"
        f"Blocked on feedback. Next step is to email the project status.\n"
    )


def write_unique(path: Path, item: Planned, ordinal: dict[str, int], seed: int) -> None:
    # These files use their own wording so the usual templates do not add rule keywords.
    if item.name in HARD_TEXT:
        text = HARD_TEXT[item.name]
        if path.suffix.lower() == ".pdf":
            write_pdf(path, text)
        else:
            write_docx(path, text)
        return
    ordinal[item.category] = ordinal.get(item.category, 0)
    index = ordinal[item.category]
    ordinal[item.category] += 1
    if item.category == "Receipts":
        write_pdf(path, receipt_text(item.name, index, item.when))
    elif item.category == "School":
        write_docx(path, school_text(index))
    elif item.category == "Work":
        write_docx(path, work_text(index))
    elif item.category == "Screenshots":
        write_screenshot(path, item.when, seed)
    elif item.category == "Photos":
        write_photo(path, index, seed)
    elif item.category == "Installers":
        write_installer(path)
    elif item.category == "Archives":
        write_archive(path)
    elif item.category == "Other":
        write_other(path, index)
    else:
        die(f"No writer for {item.category}")


def write_plans(folder: Path, plans: list[Planned], seed: int) -> None:
    written: dict[str, Path] = {}
    ordinal: dict[str, int] = {}
    for item in plans:
        if item.category not in CATEGORIES:
            die(f"{item.name} has an unknown category: {item.category}")
        path = inside_folder(folder, item.name)
        if item.source is None:
            write_unique(path, item, ordinal, seed)
        else:
            shutil.copyfile(written[item.source], path)
        stamp(path, item.when)
        written[item.name] = path


def write_labels(path: Path, plans: list[Planned]) -> None:
    # Beside the test folder, not inside it, so the answer key is not one of the downloads.
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "true_category", "is_duplicate"])
        for item in plans:
            # source is set only when this file is a byte copy of another file.
            writer.writerow([item.name, item.category, "yes" if item.source else "no"])


def report(folder: Path, labels_path: Path, plans: list[Planned]) -> None:
    print(f"Created {len(plans)} files in {folder}")
    copies = sum(1 for item in plans if item.source)
    print(f"Exact copies: {copies}")
    tally = {category: 0 for category in CATEGORIES}
    for item in plans:
        tally[item.category] += 1
    for category in CATEGORIES:
        print(f"  {category}: {tally[category]}")
    print(f"Labels: {labels_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fill TEST_FOLDER with messy sample files and write labels.csv beside it."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=50,
        help="How many files to make (default: 50)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42). The same seed rebuilds the same folder.",
    )
    args = parser.parse_args()
    if args.count < 1:
        die("--count must be at least 1.")
    return args


def check_mix() -> None:
    names = {name for name, _ in MIX if name != "duplicates"}
    if names != set(CATEGORIES):
        die("MIX and CATEGORIES do not match.")
    if sum(weight for _, weight in MIX) != 100:
        die("MIX weights must sum to 100.")


def main() -> None:
    check_mix()
    args = parse_args()
    count = args.count
    folder = Path(TEST_FOLDER)
    labels_path = folder.parent / "labels.csv"
    assert_sandbox(folder)
    assert_can_fill(folder, labels_path)
    counts = allocate(count)
    if sum(counts.values()) != count:
        die("File mix does not add up to --count.")
    rng = random.Random(args.seed)
    plans = build_plans(counts, make_dates(count, rng))
    if len(plans) != count:
        die("Planned file count does not match --count.")
    plans.extend(typo_plans(rng, plans))
    plans.extend(hard_plans(rng))
    folder.mkdir(parents=True, exist_ok=True)
    write_plans(folder, plans, args.seed)
    write_labels(labels_path, plans)
    report(folder, labels_path, plans)


if __name__ == "__main__":
    main()
