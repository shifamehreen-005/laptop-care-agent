"""Grade the sorter against an answer key (labels.csv).

Read-only: nothing inside the tested folder is moved, renamed, deleted or written.
Results are saved in evals/, which must sit outside the tested folder.
"""

import csv
import io
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import classifier
from config import CATEGORIES, MODELS
from scanner import scan_folder
from verify import compare, snapshot

RULES_ONLY = "Rules only"
SETUPS = [RULES_ONLY] + list(MODELS)
EVALS_DIR = Path(__file__).resolve().parent / "evals"
OLLAMA_BASE = "http://127.0.0.1:11434"
NO_OLLAMA = "Ollama isn't running, so only Rules only ran. Start Ollama to compare models."
NO_ANSWER = "Ollama did not answer"
# A stalled model would otherwise wait the full timeout on every file.
MAX_SILENT_FILES = 3
LIST_LIMIT = 10


class ModelStopped(Exception):
    """The model stopped answering partway through a setup."""


def run_eval(folder, labels_path, setups, with_reason=True, progress=None, seed=None, out_dir=EVALS_DIR) -> dict:
    """Run each setup on every labeled file and score it.

    with_reason is True, False, or (True, False) to run both prompts while each model is loaded.
    progress(setup_name, done, total) is called with done=0 when a setup starts, then after each file.
    """
    folder = Path(folder).resolve()
    labels_path = Path(labels_path)
    out_dir = Path(out_dir).resolve()
    if out_dir == folder or folder in out_dir.parents:
        raise ValueError("Results can't be saved inside the folder being tested.")
    variants = (with_reason,) if isinstance(with_reason, bool) else tuple(with_reason)
    if any(setup != RULES_ONLY for setup in setups):
        check_prompt_file()
    labels, has_dup_column = read_labels(labels_path)
    before = snapshot(folder)
    records = scan_folder(folder)
    warnings = label_warnings(records, labels)
    skipped: list[str] = []
    runs_to_do = plan_runs(setups, variants, skipped)

    graded = graded_records(records, labels, warnings)
    to_sort = [record for record in graded if labels[record["name"]]["is_duplicate"] != "yes"]
    answers: dict[str, dict[str, dict]] = {record["name"]: {} for record in graded}
    runs = []
    for setup, prompts in runs_to_do:
        if setup == RULES_ONLY:
            runs.append(run_setup(setup, None, to_sort, labels, answers, progress))
            continue
        runs.extend(run_model(setup, prompts, to_sort, labels, answers, progress, skipped))
    for run in runs:
        if run["no_answer"]:
            warnings.append(f"{run['name']}: {run['no_answer']} files got no answer from Ollama (counted as Review).")

    after = snapshot(folder)
    changes = compare(before, after)
    results = {
        "run_id": datetime.now().strftime("%Y-%m-%d_%H%M%S"),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "folder": str(folder),
        "labels": str(labels_path),
        "file_count": len(records),
        "sorted_count": len(to_sort),
        "prompt": prompt_label(variants),
        "seed": seed,
        "warnings": warnings,
        "skipped": skipped,
        "runs": runs,
        "duplicates": score_duplicates(graded, labels) if has_dup_column else None,
        "rows": file_rows(graded, labels, answers),
        "folder_unchanged": not changes,
        "folder_changes": changes,
        "csv_path": "",
        "md_path": "",
    }
    try:
        save_results(results, out_dir)
    except OSError:
        warnings.append(f"The results couldn't be saved in {out_dir}. Use Download results instead.")
    return results


def check_prompt_file() -> None:
    # Without it every AI answer would be Review, which would look like a real score.
    try:
        classifier.build_prompt("name", "text", ".txt", True)
    except (OSError, KeyError, IndexError, ValueError) as err:
        raise ValueError(f"The prompt file {classifier.PROMPT_FILE} is missing or broken.") from err


def read_labels(path: Path) -> tuple[dict[str, dict], bool]:
    """filename -> {true_category, is_duplicate}. A blank is_duplicate counts as no."""
    if not path.is_file():
        raise ValueError(f"No labels file at {path}.")
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames or []
            rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as err:
        raise ValueError("The labels file couldn't be read. Save it as a UTF-8 CSV.") from err
    if "filename" not in columns or "true_category" not in columns:
        raise ValueError("The labels file needs filename and true_category columns.")
    labels = {}
    for row in rows:
        name = (row.get("filename") or "").strip()
        if not name:
            continue
        duplicate = (row.get("is_duplicate") or "").strip().lower()
        difficulty = (row.get("difficulty") or "").strip().lower()
        if difficulty not in {"clear", "edge", "normal"}:
            difficulty = "normal"
        labels[name] = {
            "true_category": (row.get("true_category") or "").strip(),
            "is_duplicate": "yes" if duplicate == "yes" else "no",
            "difficulty": difficulty,
        }
    if not labels:
        raise ValueError("The labels file has no labels in it.")
    return labels, "is_duplicate" in columns


def short_list(names: list[str]) -> str:
    shown = ", ".join(names[:LIST_LIMIT])
    if len(names) > LIST_LIMIT:
        shown += f" and {len(names) - LIST_LIMIT} more"
    return shown


def label_warnings(records: list[dict], labels: dict) -> list[str]:
    warnings = []
    names = {record["name"] for record in records}
    unlabeled = sorted(names - set(labels))
    if unlabeled:
        warnings.append(f"{len(unlabeled)} files have no label and weren't graded: {short_list(unlabeled)}")
    missing = sorted(set(labels) - names)
    if missing:
        warnings.append(f"{len(missing)} labels have no file in the folder: {short_list(missing)}")
    known = set(CATEGORIES) | {"Review"}
    odd = sorted(name for name, label in labels.items() if label["true_category"] not in known)
    if odd:
        warnings.append(
            f"{len(odd)} labels aren't a known category, so no setup can get them right: {short_list(odd)}"
        )
    if any(record.get("folder") for record in records):
        warnings.append("Some files sit inside subfolders, so this folder isn't freshly generated.")
    return warnings


def graded_records(records: list[dict], labels: dict, warnings: list[str]) -> list[dict]:
    """Labeled files, one per name. Labels are by name, so a second file with that name can't be graded."""
    graded = []
    seen: set[str] = set()
    repeated = []
    for record in records:
        name = record["name"]
        if name not in labels:
            continue
        if name in seen:
            repeated.append(f"{record.get('folder')}/{name}")
            continue
        seen.add(name)
        graded.append(record)
    if repeated:
        warnings.append(f"These share a name with another file and weren't graded: {short_list(repeated)}")
    return graded


def plan_runs(setups, variants, skipped: list[str]) -> list[tuple[str, tuple]]:
    """Which setups can run. Missing models are skipped with the command that fixes it."""
    wanted = [setup for setup in SETUPS if setup in setups]
    models = [setup for setup in wanted if setup != RULES_ONLY]
    if not models:
        return [(RULES_ONLY, ())] if RULES_ONLY in wanted else []
    downloaded = downloaded_models()
    if downloaded is None:
        skipped.append(NO_OLLAMA)
        return [(RULES_ONLY, ())]
    runs = [(RULES_ONLY, ())] if RULES_ONLY in wanted else []
    for model in models:
        if model in downloaded:
            runs.append((model, variants))
        else:
            skipped.append(f"{model} isn't downloaded. Run: ollama pull {model}")
    if any(setup != RULES_ONLY for setup, _prompts in runs):
        unload_all()
    return runs


def run_model(setup, prompts, to_sort, labels, answers, progress, skipped) -> list[dict]:
    """Warm up, run each prompt, then unload, even if a run stops partway."""
    runs = []
    try:
        if progress is not None:
            progress(run_name(setup, prompts[0]), 0, len(to_sort))
        if not warm_up(setup):
            skipped.append(f"{setup} didn't answer, so it was skipped.")
            return runs
        for prompt in prompts:
            try:
                runs.append(run_setup(setup, prompt, to_sort, labels, answers, progress))
            except ModelStopped:
                name = run_name(setup, prompt)
                for per_file in answers.values():
                    per_file.pop(name, None)
                skipped.append(f"{name} stopped answering, so it was skipped.")
                break
    finally:
        # An 8 GB laptop can't hold two models at once.
        unload(setup)
    return runs


def run_setup(setup, prompt, to_sort, labels, answers, progress) -> dict:
    name = run_name(setup, prompt)
    counts = {"correct": 0, "review": 0, "wrong": 0, "ai_files": 0, "ai_correct": 0, "ai_wrong": 0, "no_answer": 0}
    ai_events = []
    ai_seconds = 0.0
    silent = 0
    started = time.perf_counter()
    if progress is not None:
        progress(name, 0, len(to_sort))
    for done, record in enumerate(to_sort, start=1):
        clock = time.perf_counter()
        if setup == RULES_ONLY:
            category, reason, source = classifier.classify(record, use_ai=False)
        else:
            category, reason, source = classifier.classify(
                record,
                use_ai=True,
                model=setup,
                with_reason=prompt,
                timeout=classifier.SLOW_TIMEOUT_SECONDS,
            )
        spent = time.perf_counter() - clock
        # Files the rules decide never reach the model, so they don't reset the count.
        if source == "ai" and reason.startswith(NO_ANSWER):
            silent += 1
            counts["no_answer"] += 1
            if silent >= MAX_SILENT_FILES:
                raise ModelStopped(name)
        elif source == "ai":
            silent = 0
        label = labels[record["name"]]
        truth = label["true_category"]
        verdict = grade(category, truth)
        counts[verdict] += 1
        if source == "ai":
            ai_seconds += spent
            counts["ai_files"] += 1
            if verdict == "correct":
                counts["ai_correct"] += 1
            elif verdict == "wrong":
                counts["ai_wrong"] += 1
            # Only AI-decided files count toward category / difficulty accuracy.
            ai_events.append(
                {
                    "category": truth,
                    "difficulty": label.get("difficulty") or "normal",
                    "correct": verdict == "correct",
                }
            )
        answers[record["name"]][name] = {"answer": category, "source": source, "reason": reason}
        if progress is not None:
            progress(name, done, len(to_sort))
    total = len(to_sort)
    by_category, by_difficulty = summarize_ai_slices(ai_events)
    return {
        "name": name,
        "setup": setup,
        "prompt": "none" if setup == RULES_ONLY else prompt_label((prompt,)),
        **counts,
        "sorted_total": total,
        "accuracy": round(100 * counts["correct"] / total, 1) if total else 0.0,
        "seconds_per_ai_file": round(ai_seconds / counts["ai_files"], 2) if counts["ai_files"] else 0.0,
        "total_seconds": round(time.perf_counter() - started, 1),
        "by_category": by_category,
        "by_difficulty": by_difficulty,
    }


def summarize_ai_slices(events: list[dict]) -> tuple[dict, dict]:
    """Accuracy by true category and by difficulty, for AI-decided files only."""
    by_category: dict[str, dict] = {}
    by_difficulty: dict[str, dict] = {}
    for event in events:
        for bag, key in ((by_category, event["category"]), (by_difficulty, event["difficulty"])):
            slot = bag.setdefault(key, {"correct": 0, "total": 0})
            slot["total"] += 1
            if event["correct"]:
                slot["correct"] += 1
    for bag in (by_category, by_difficulty):
        for slot in bag.values():
            slot["accuracy"] = round(100 * slot["correct"] / slot["total"], 1) if slot["total"] else 0.0
    return by_category, by_difficulty


def grade(answer: str, truth: str) -> str:
    # Review asks the user. A wrong real folder hides the file, so it is counted apart.
    if answer == truth:
        return "correct"
    if answer == "Review":
        return "review"
    return "wrong"


def score_duplicates(graded: list[dict], labels: dict) -> dict:
    found = missed = wrongly_flagged = 0
    for record in graded:
        truth = labels[record["name"]]["is_duplicate"] == "yes"
        flagged = bool(record.get("is_duplicate"))
        if truth and flagged:
            found += 1
        elif truth:
            missed += 1
        elif flagged:
            wrongly_flagged += 1
    return {"found": found, "missed": missed, "wrongly_flagged": wrongly_flagged}


# Short notes for the hard files the rules cannot catch by keyword.
WHY_TRUE_FILES = {
    "Document (3).docx": "history essay for class",
    "scan_0042.pdf": "lease, not school/work",
    "doc1.docx": "job cover letter",
    "payment_aug.pdf": "gym payment receipt",
    "reading.docx": "reading summary for class",
    "homewrok.docx": "homework (typo name)",
    "inovice_march.pdf": "invoice (typo name)",
}


def why_true_note(record: dict, label: dict) -> str:
    """One short phrase for why the answer key picked that folder."""
    if label["is_duplicate"] == "yes":
        return "exact copy"
    name = record["name"]
    if name in WHY_TRUE_FILES:
        return WHY_TRUE_FILES[name]
    category = label["true_category"]
    extension = (record.get("extension") or "").lower()
    if category == "Installers":
        return f"{extension} installer"
    if category == "Archives":
        return f"{extension} archive"
    if category == "Photos":
        return "photo file"
    if category == "Screenshots":
        return "Screenshot name"
    if category == "Receipts":
        return "invoice/receipt text"
    if category == "School":
        return "class/homework text"
    if category == "Work":
        return "job/meeting text"
    if category == "Other":
        return "fits none of the rest"
    return category


def file_rows(graded, labels, answers) -> list[dict]:
    rows = []
    for record in graded:
        label = labels[record["name"]]
        rows.append(
            {
                "file": record["name"],
                "true_label": label["true_category"],
                "why_true": why_true_note(record, label),
                "difficulty": label.get("difficulty") or "normal",
                "is_duplicate": label["is_duplicate"],
                "found_duplicate": "yes" if record.get("is_duplicate") else "no",
                "answers": answers[record["name"]],
            }
        )
    return rows


def run_name(setup: str, prompt) -> str:
    if setup == RULES_ONLY:
        return RULES_ONLY
    # Short, so chart labels aren't cut to look the same.
    return f"{setup} ({'reason' if prompt else 'no reason'})"


def prompt_label(variants) -> str:
    if len(variants) > 1:
        return "both"
    return "with reason" if variants[0] else "without reason"


def ollama_get(path: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}{path}", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def ollama_post(path: str, body: dict, timeout: float) -> dict | None:
    request = urllib.request.Request(
        f"{OLLAMA_BASE}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def downloaded_models() -> set[str] | None:
    """Model names Ollama has, or None when Ollama isn't running."""
    payload = ollama_get("/api/tags")
    if payload is None:
        return None
    return {str(model.get("name") or "") for model in payload.get("models") or [] if isinstance(model, dict)}


def warm_up(model: str) -> bool:
    # Loading the model is slow and would count against the first file.
    body = {"model": model, "prompt": "OK", "stream": False, "keep_alive": "30m", "options": {"num_predict": 1}}
    return ollama_post("/api/generate", body, classifier.SLOW_TIMEOUT_SECONDS) is not None


def unload(model: str) -> None:
    ollama_post("/api/generate", {"model": model, "keep_alive": 0}, 30)


def unload_all() -> None:
    """Free memory the app's model may still hold before the first model loads."""
    payload = ollama_get("/api/ps")
    if payload is None:
        return
    for model in payload.get("models") or []:
        name = str(model.get("name") or "") if isinstance(model, dict) else ""
        if name:
            unload(name)


def save_results(results: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # A new name each run, so earlier runs stay for comparison.
    stem = f"results_{results['run_id']}"
    number = 2
    while (out_dir / f"{stem}.csv").exists() or (out_dir / f"{stem}.md").exists():
        stem = f"results_{results['run_id']}_{number}"
        number += 1
    csv_path = out_dir / f"{stem}.csv"
    md_path = out_dir / f"{stem}.md"
    csv_path.write_text(csv_text(results), encoding="utf-8", newline="")
    md_path.write_text(summary_markdown(results), encoding="utf-8")
    results["csv_path"] = str(csv_path)
    results["md_path"] = str(md_path)


def csv_text(results: dict) -> str:
    """Per-file rows: file, true label, why true, difficulty, duplicates, then answer/source/reason."""
    names = [run["name"] for run in results["runs"]]
    header = ["file", "true_label", "why_true", "difficulty", "is_duplicate", "found_duplicate"]
    for name in names:
        header += [f"{name} answer", f"{name} source", f"{name} reason"]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in results["rows"]:
        line = [
            row["file"],
            row["true_label"],
            row.get("why_true", ""),
            row.get("difficulty", "normal"),
            row["is_duplicate"],
            row["found_duplicate"],
        ]
        for name in names:
            answer = row["answers"].get(name) or {}
            line += [answer.get("answer", ""), answer.get("source", ""), answer.get("reason", "")]
        writer.writerow(line)
    return buffer.getvalue()


def summary_table(results: dict) -> str:
    lines = [
        "| Setup | Prompt | Correct | Review | Wrong moves | Accuracy % | AI correct / AI files "
        "| Sec per AI file | Total time (s) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for run in results["runs"]:
        lines.append(
            f"| {run['setup']} | {run['prompt']} | {run['correct']} | {run['review']} | {run['wrong']} "
            f"| {run['accuracy']} | {run['ai_correct']} / {run['ai_files']} "
            f"| {run['seconds_per_ai_file']} | {run['total_seconds']} |"
        )
    return "\n".join(lines)


def slice_table(title: str, runs: list[dict], field: str, key_order: list[str] | None = None) -> str:
    """Markdown table of AI-only accuracy by category or difficulty."""
    keys: list[str] = []
    seen: set[str] = set()
    if key_order:
        for key in key_order:
            if any(key in (run.get(field) or {}) for run in runs):
                keys.append(key)
                seen.add(key)
    for run in runs:
        for key in run.get(field) or {}:
            if key not in seen:
                keys.append(key)
                seen.add(key)
    if not keys:
        return f"### {title}\n\nNo AI-decided files.\n"
    header = "| Setup | " + " | ".join(keys) + " |"
    rule = "|" + "---|" * (len(keys) + 1)
    lines = [f"### {title}", "", header, rule]
    for run in runs:
        bag = run.get(field) or {}
        cells = []
        for key in keys:
            slot = bag.get(key)
            if not slot:
                cells.append("—")
            else:
                cells.append(f"{slot['correct']}/{slot['total']} ({slot['accuracy']}%)")
        lines.append(f"| {run['name']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def duplicate_line(results: dict) -> str:
    dup = results["duplicates"]
    if dup is None:
        return "Duplicates: not scored (the labels file has no is_duplicate column)."
    return f"Duplicates: {dup['found']} found, {dup['missed']} missed, {dup['wrongly_flagged']} wrongly flagged."


PROMPT_MEANING = (
    "**Prompt meaning:** `with reason` / `(reason)` asks the model for a short why, then the folder. "
    "`without reason` / `(no reason)` asks for the folder only. Rules only never asks the model."
)


def summary_markdown(results: dict) -> str:
    parts = [
        f"# Eval {results['date']}",
        "",
        PROMPT_MEANING,
        "",
        f"- Folder: {results['folder']}",
        f"- Labels: {results['labels']}",
        f"- Files: {results['file_count']} ({results['sorted_count']} graded for sorting, duplicates excluded)",
        f"- Prompt: {results['prompt']}",
        f"- Seed: {results['seed'] if results['seed'] is not None else 'unknown'}",
        f"- Folder unchanged: {'yes' if results['folder_unchanged'] else 'NO'}",
        "",
        summary_table(results),
        "",
        slice_table(
            "AI accuracy by category (AI-decided files only)",
            results["runs"],
            "by_category",
            ["Receipts", "School", "Work", "Other", "Screenshots", "Installers", "Archives", "Photos"],
        ),
        "",
        slice_table(
            "AI accuracy by difficulty (AI-decided files only)",
            results["runs"],
            "by_difficulty",
            ["clear", "edge", "normal"],
        ),
        "",
        duplicate_line(results),
    ]
    notes = results["skipped"] + results["warnings"]
    if notes:
        parts += ["", "Notes:"] + [f"- {note}" for note in notes]
    return "\n".join(parts) + "\n"
