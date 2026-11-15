"""Eval scoring on a small fake folder with a fake model. No Ollama needed."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import classifier
import evaluate
from verify import snapshot

# name -> (text, true_category, is_duplicate)
FILES = {
    "invoice.txt": ("invoice for the new desk, 20 dollars", "Receipts", "no"),
    "gym.txt": ("PAYMENT from City Gym. Total paid 42.12. Card ending 4242.", "Receipts", "no"),
    "essay.txt": ("History essay about Rome and its roads for the Friday class.", "School", "no"),
    "essay (1).txt": ("History essay about Rome and its roads for the Friday class.", "School", "yes"),
    "short.txt": ("hi", "Other", "no"),
    "notes.txt": ("random words that mean nothing to anyone at all", "Other", "no"),
    "copy.txt": ("labeled as a copy but nothing else has these bytes", "Other", "yes"),
    "twin_a.txt": ("meeting notes for monday", "Work", "no"),
    "twin_b.txt": ("meeting notes for monday", "Work", "no"),
}
# What the fake model answers for files no rule decides.
FAKE_ANSWERS = {"gym.txt": "Other", "essay.txt": "School", "notes.txt": "Review"}


def make_folder(tmp_path: Path) -> tuple[Path, Path]:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    for name, (text, _category, _dup) in FILES.items():
        (folder / name).write_text(text, encoding="utf-8")
    labels = tmp_path / "labels.csv"
    with labels.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["filename", "true_category", "is_duplicate"])
        for name, (_text, category, dup) in FILES.items():
            writer.writerow([name, category, dup])
    return folder, labels


def fake_model(monkeypatch, downloaded=frozenset({"llama3.2:1b"}), answers=None):
    table = answers if answers is not None else FAKE_ANSWERS

    def ask(name, preview, extension="", model=None, with_reason=True, timeout=0):
        category = table[name]
        return category, f"ai: fake said {category}", "ai"

    monkeypatch.setattr(classifier, "ask_model", ask)
    monkeypatch.setattr(evaluate, "downloaded_models", lambda: None if downloaded is None else set(downloaded))
    monkeypatch.setattr(evaluate, "warm_up", lambda model: True)
    monkeypatch.setattr(evaluate, "unload", lambda model: None)
    monkeypatch.setattr(evaluate, "unload_all", lambda: None)


def test_scoring_and_folder_unchanged(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    folder, labels = make_folder(tmp_path)
    before = snapshot(folder)
    calls = []
    results = evaluate.run_eval(
        folder,
        labels,
        ["Rules only", "llama3.2:1b"],
        progress=lambda setup, done, total: calls.append((setup, done, total)),
        out_dir=tmp_path / "evals",
    )
    assert snapshot(folder) == before
    assert results["folder_unchanged"] is True
    assert results["sorted_count"] == 7
    rules, model = results["runs"]

    # Rules decide invoice and both meeting notes. Everything else goes to Review.
    assert (rules["correct"], rules["review"], rules["wrong"]) == (3, 4, 0)
    assert rules["accuracy"] == 42.9
    assert rules["ai_files"] == 0

    # The model fixes the essay, files the gym payment wrongly, and sends the vague note to Review.
    assert model["name"] == "llama3.2:1b (reason)"
    assert (model["correct"], model["review"], model["wrong"]) == (4, 2, 1)
    assert model["accuracy"] == 57.1
    assert (model["ai_files"], model["ai_correct"], model["ai_wrong"]) == (3, 1, 1)

    assert ("llama3.2:1b (reason)", 0, 7) in calls
    assert calls[-1] == ("llama3.2:1b (reason)", 7, 7)
    assert Path(results["csv_path"]).parent == tmp_path / "evals"
    assert Path(results["md_path"]).is_file()
    gym = next(row for row in results["rows"] if row["file"] == "gym.txt")
    assert gym["answers"]["llama3.2:1b (reason)"]["reason"] == "ai: fake said Other"


def test_duplicate_scoring(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    folder, labels = make_folder(tmp_path)
    results = evaluate.run_eval(folder, labels, ["Rules only"], out_dir=tmp_path / "evals")
    # essay (1) is found, copy.txt is missed, one of the twins is flagged though labeled no.
    assert results["duplicates"] == {"found": 1, "missed": 1, "wrongly_flagged": 1}


def test_missing_model_is_skipped(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    folder, labels = make_folder(tmp_path)
    results = evaluate.run_eval(folder, labels, ["Rules only", "llama3.2:3b"], out_dir=tmp_path / "evals")
    assert "llama3.2:3b isn't downloaded. Run: ollama pull llama3.2:3b" in results["skipped"]
    assert [run["name"] for run in results["runs"]] == ["Rules only"]


def test_no_ollama_runs_rules_only(tmp_path, monkeypatch):
    fake_model(monkeypatch, downloaded=None)
    folder, labels = make_folder(tmp_path)
    results = evaluate.run_eval(folder, labels, ["llama3.2:1b"], out_dir=tmp_path / "evals")
    assert results["skipped"] == [evaluate.NO_OLLAMA]
    assert [run["name"] for run in results["runs"]] == ["Rules only"]


def test_results_never_saved_inside_folder(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    folder, labels = make_folder(tmp_path)
    try:
        evaluate.run_eval(folder, labels, ["Rules only"], out_dir=folder / "evals")
    except ValueError:
        pass
    else:
        raise AssertionError("results were allowed inside the tested folder")
    assert not (folder / "evals").exists()


def test_model_stops_after_silent_files(tmp_path, monkeypatch):
    fake_model(monkeypatch)

    def silent(name, preview, extension="", model=None, with_reason=True, timeout=0):
        return "Review", f"{evaluate.NO_ANSWER} (TimeoutError)", "ai"

    monkeypatch.setattr(classifier, "ask_model", silent)
    folder, labels = make_folder(tmp_path)
    unloaded = []
    monkeypatch.setattr(evaluate, "unload", lambda model: unloaded.append(model))
    results = evaluate.run_eval(folder, labels, ["llama3.2:1b"], out_dir=tmp_path / "evals")
    assert any("stopped answering" in note for note in results["skipped"])
    assert results["runs"] == []
    assert unloaded == ["llama3.2:1b"]
    for row in results["rows"]:
        assert "llama3.2:1b (reason)" not in row["answers"]


def test_warmup_failure_unloads(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    monkeypatch.setattr(evaluate, "warm_up", lambda model: False)
    unloaded = []
    monkeypatch.setattr(evaluate, "unload", lambda model: unloaded.append(model))
    folder, labels = make_folder(tmp_path)
    results = evaluate.run_eval(folder, labels, ["llama3.2:1b"], out_dir=tmp_path / "evals")
    assert "llama3.2:1b didn't answer, so it was skipped." in results["skipped"]
    assert results["runs"] == []
    assert unloaded == ["llama3.2:1b"]


def test_duplicate_names_are_warned(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    folder, labels = make_folder(tmp_path)
    nested = folder / "Work"
    nested.mkdir()
    (nested / "invoice.txt").write_text("invoice for a second desk", encoding="utf-8")
    results = evaluate.run_eval(folder, labels, ["Rules only"], out_dir=tmp_path / "evals")
    assert any("share a name" in note for note in results["warnings"])
    assert sum(1 for row in results["rows"] if row["file"] == "invoice.txt") == 1


def test_unknown_category_is_warned(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    folder, labels = make_folder(tmp_path)
    with labels.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["mystery.txt", "NotAFolder", "no"])
    (folder / "mystery.txt").write_text("enough text to be graded as a normal file here", encoding="utf-8")
    results = evaluate.run_eval(folder, labels, ["Rules only"], out_dir=tmp_path / "evals")
    assert any("aren't a known category" in note for note in results["warnings"])


def test_missing_prompt_file_stops_ai_eval(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    monkeypatch.setattr(classifier, "PROMPT_FILE", tmp_path / "missing_prompt.txt")
    folder, labels = make_folder(tmp_path)
    try:
        evaluate.run_eval(folder, labels, ["llama3.2:1b"], out_dir=tmp_path / "evals")
    except ValueError as err:
        assert "prompt file" in str(err)
    else:
        raise AssertionError("missing prompt file was allowed")


def test_both_prompts_share_one_load(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    warmed = []
    unloaded = []
    monkeypatch.setattr(evaluate, "warm_up", lambda model: warmed.append(model) or True)
    monkeypatch.setattr(evaluate, "unload", lambda model: unloaded.append(model))
    folder, labels = make_folder(tmp_path)
    results = evaluate.run_eval(
        folder, labels, ["llama3.2:1b"], with_reason=(True, False), out_dir=tmp_path / "evals"
    )
    assert warmed == ["llama3.2:1b"]
    assert unloaded == ["llama3.2:1b"]
    assert [run["name"] for run in results["runs"]] == ["llama3.2:1b (reason)", "llama3.2:1b (no reason)"]


def test_csv_download_text(tmp_path, monkeypatch):
    fake_model(monkeypatch)
    folder, labels = make_folder(tmp_path)
    results = evaluate.run_eval(folder, labels, ["Rules only"], out_dir=tmp_path / "evals")
    text = evaluate.csv_text(results)
    assert text.startswith("file,true_label,why_true,difficulty,is_duplicate,found_duplicate")
    assert "invoice.txt,Receipts,invoice/receipt text,normal,no," in text
    assert "Prompt meaning:" in Path(results["md_path"]).read_text(encoding="utf-8")
    assert "AI accuracy by difficulty" in Path(results["md_path"]).read_text(encoding="utf-8")
