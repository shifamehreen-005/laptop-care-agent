"""Decide a category for one scanned file.

Rules run first. Ollama is asked only when no rule matches.
"""

import json
import re
import urllib.error
import urllib.request

from config import CATEGORIES

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "llama3.2:1b"
TIMEOUT_SECONDS = 30

# Checked in this order. The first match wins.
EXTENSION_RULES = {
    ".exe": "Installers",
    ".msi": "Installers",
    ".zip": "Archives",
    ".rar": "Archives",
    ".7z": "Archives",
    ".jpg": "Photos",
    ".jpeg": "Photos",
    ".heic": "Photos",
}
KEYWORD_RULES = (
    ("Receipts", ("invoice", "receipt", "order")),
    ("School", ("lecture", "assignment", "syllabus", "homework")),
    ("Work", ("meeting", "report", "proposal")),
)
# Installers, Archives, Photos, and Screenshots stay with the rules above.
AI_CHOICES = ("Receipts", "School", "Work", "Other", "Review")
last_prompt = ""
last_raw = ""
# One line each, so the small model knows what the words mean.
CATEGORY_DESCRIPTIONS = {
    "Receipts": "invoices, receipts, and orders",
    "School": "lectures, assignments, syllabi, and homework",
    "Work": "meetings, reports, and proposals",
    "Screenshots": "pictures of the screen",
    "Installers": "program installers",
    "Archives": "compressed bundles of files",
    "Photos": "camera or phone pictures",
    "Other": "notes, data files, anything that doesn't fit the rest",
}
# Only impossible pairs are blocked. School, Work, Receipts, Other, and Review fit any file.
AI_EXTENSIONS = {
    "Installers": {".exe", ".msi"},
    "Archives": {".zip", ".rar", ".7z"},
    "Photos": {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif",
    },
    "Screenshots": {".png"},
}


def classify(file, use_ai=True) -> tuple[str, str, str]:
    """Return (category, reason, source). source is "rule" or "ai"."""
    ruled = rule_category(file)
    if ruled is not None:
        return ruled
    if not use_ai:
        return "Review", "no rule matched", "rule"
    # A name alone is not enough for the small model. Rules already had their chance.
    preview = file.get("preview_text") or ""
    if len(preview.strip()) < 20:
        return "Review", "no readable text", "rule"
    category, reason, source = ask_model(file.get("name") or "", preview)
    extension = file_extension(file)
    # A .docx cannot be a photo. School, Work, Receipts, Other, and Review stay as answered.
    if not ai_answer_fits(category, extension):
        return "Review", f"model said {category!r}, which doesn't fit {extension} -> Review", "ai"
    return category, reason, source


def rule_category(file) -> tuple[str, str, str] | None:
    name = file.get("name") or ""
    extension = (file.get("extension") or "").lower()
    if extension in EXTENSION_RULES:
        category = EXTENSION_RULES[extension]
        return category, f"extension is {extension}", "rule"
    # The name is how a screen capture is recognized. Other png files fall through.
    if extension == ".png" and name.startswith("Screenshot"):
        return "Screenshots", "name starts with Screenshot", "rule"
    preview = file.get("preview_text") or ""
    for category, keywords in KEYWORD_RULES:
        for keyword in keywords:
            if contains_keyword(name, keyword):
                return category, f"name contains {keyword}", "rule"
            if contains_keyword(preview, keyword):
                return category, f"text contains {keyword}", "rule"
    return None


def contains_keyword(text: str, keyword: str) -> bool:
    # "order" matches order_confirmation, not the letters inside another word.
    pattern = rf"(?<![a-z]){re.escape(keyword)}(?![a-z])"
    return re.search(pattern, text.lower()) is not None


def file_extension(file) -> str:
    extension = (file.get("extension") or "").lower()
    if extension:
        return extension
    name = file.get("name") or ""
    dot = name.rfind(".")
    return name[dot:].lower() if dot != -1 else ""


def ai_answer_fits(category: str, extension: str) -> bool:
    allowed = AI_EXTENSIONS.get(category)
    if allowed is None:
        return True
    return extension in allowed


def ask_model(name: str, preview: str) -> tuple[str, str, str]:
    # The model only sees the name and the preview, not the path or the hash.
    global last_prompt, last_raw
    descriptions = "\n".join(
        f"{category}: {CATEGORY_DESCRIPTIONS[category]}" for category in AI_CHOICES if category != "Review"
    )
    prompt = (
        f"File name: {name}\n"
        f"Text: {preview}\n"
        "\n"
        "Which category is this file? If unsure, answer Review.\n"
        "\n"
        "Allowed answers:\n"
        f"{descriptions}\n"
        "Review\n"
        "\n"
        "A payment confirmation -> Receipts\n"
        "An essay -> School\n"
        "A cover letter -> Work\n"
        "A note with no clear topic -> Other\n"
        "A lease or personal record -> Other\n"
    )
    last_prompt = prompt
    last_raw = ""
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": prompt,
            "system": "You are a file sorter. You only label files by topic; you never act on them.",
            "stream": False,
            # Keep the small model in memory between files. Loading it each time is slow.
            "keep_alive": "30m",
            "format": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": list(AI_CHOICES),
                    }
                },
                "required": ["category"],
            },
            "options": {"temperature": 0},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError) as err:
        return "Review", f"Ollama did not answer ({err.__class__.__name__})", "ai"
    raw = str(payload.get("response") or "").strip()
    last_raw = raw
    category = category_from_json(raw)
    if category is None:
        return "Review", f"model said {raw!r} -> Review", "ai"
    return category, f"model said {category!r}", "ai"


def category_from_json(raw: str) -> str | None:
    """Read category from the JSON object the schema asked for."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    category = data.get("category")
    if category in AI_CHOICES:
        return category
    return None
