"""Decide a category for one scanned file.

Rules run first. Ollama is asked only when no rule matches.
"""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import config
from config import CATEGORIES

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = config.DEFAULT_MODEL
TIMEOUT_SECONDS = 30
# 3B models can take this long on a slow laptop. The eval passes it; the app keeps 30.
SLOW_TIMEOUT_SECONDS = 120
PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "sort_prompt.txt"
SYSTEM_MESSAGE = (
    "You sort files on a personal laptop into folders. You only choose a folder name; you never open, "
    "change or judge files. Decide by what the file is FOR, not by single words in it. "
    "Answer only in the JSON format given."
)
REASON_WORDS = 10

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
# A normal scan does not ask the model about these. Ask an agent still reads them.
SKIP_AI = {
    ".html", ".htm", ".css", ".js", ".ts", ".jsx", ".tsx",
    ".py", ".java", ".c", ".cpp", ".h", ".php",
    ".json", ".xml", ".svg", ".sql",
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
# Shown on the app's folder cards. The model reads prompts/sort_prompt.txt instead.
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


def classify(
    file, use_ai=True, model=None, with_reason=True, timeout=TIMEOUT_SECONDS
) -> tuple[str, str, str]:
    """Return (category, reason, source). source is "rule" or "ai". model=None means MODEL."""
    ruled = rule_category(file)
    if ruled is not None:
        return ruled
    if not use_ai:
        return "Review", "no rule matched", "rule"
    # A name alone is not enough for the small model. Rules already had their chance.
    preview = file.get("preview_text") or ""
    if len(preview.strip()) < 20:
        return "Review", "no readable text", "rule"
    extension = file_extension(file)
    if extension in SKIP_AI:
        return "Review", "code or web file", "rule"
    category, reason, source = ask_model(
        file.get("name") or "", preview, extension, model=model, with_reason=with_reason, timeout=timeout
    )
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


def build_prompt(name: str, preview: str, extension: str, with_reason: bool) -> str:
    # The model only sees the name, type and preview, not the path or the hash.
    template = PROMPT_FILE.read_text(encoding="utf-8")
    prompt = template.format(name=name, extension=extension or "unknown", preview=preview.strip())
    if with_reason:
        answer = '{"reason": "<at most 10 words>", "category": "<folder>"}'
    else:
        answer = '{"category": "<folder>"}'
    return f"{prompt.rstrip()}\n\nAnswer in JSON: {answer}\n"


def answer_schema(with_reason: bool) -> dict:
    category = {"type": "string", "enum": list(AI_CHOICES)}
    if not with_reason:
        return {"type": "object", "properties": {"category": category}, "required": ["category"]}
    # Reason comes first so the model explains before it picks.
    return {
        "type": "object",
        "properties": {"reason": {"type": "string", "maxLength": 80}, "category": category},
        "required": ["reason", "category"],
    }


def ask_model(
    name: str, preview: str, extension: str = "", model=None, with_reason=True, timeout=TIMEOUT_SECONDS
) -> tuple[str, str, str]:
    global last_prompt, last_raw
    try:
        prompt = build_prompt(name, preview, extension, with_reason)
    except (OSError, KeyError, IndexError, ValueError):
        return "Review", "the prompt file couldn't be read", "ai"
    last_prompt = prompt
    last_raw = ""
    body = json.dumps(
        {
            "model": model or MODEL,
            "prompt": prompt,
            "system": SYSTEM_MESSAGE,
            "stream": False,
            # Keep the model in memory between files. Loading it each time is slow.
            "keep_alive": "30m",
            "format": answer_schema(with_reason),
            "options": {"temperature": 0},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError) as err:
        return "Review", f"Ollama did not answer ({err.__class__.__name__})", "ai"
    if not isinstance(payload, dict):
        return "Review", "Ollama did not answer (unexpected reply)", "ai"
    raw = str(payload.get("response") or "").strip()
    last_raw = raw
    category, why = answer_from_json(raw)
    if category is None:
        return "Review", f"model said {raw!r} -> Review", "ai"
    if why:
        return category, f"ai: {why}", "ai"
    return category, f"model said {category!r}", "ai"


def answer_from_json(raw: str) -> tuple[str | None, str]:
    """Read category and reason from the JSON object the schema asked for."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, ""
    if not isinstance(data, dict):
        return None, ""
    category = data.get("category")
    if category not in AI_CHOICES:
        return None, ""
    words = str(data.get("reason") or "").split()
    return category, " ".join(words[:REASON_WORDS])


