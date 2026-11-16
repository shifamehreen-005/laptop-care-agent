"""Eval screen: grade the sorter against labels.csv. Read-only for the tested folder."""

import html
from pathlib import Path

import pandas as pd
import streamlit as st

import evaluate
from config import TEST_FOLDER
from scanner import assert_readable

PROMPTS = {"With reason": True, "Without reason": False, "Both": (True, False)}
# A slow laptop: the 3B models are opt-in.
DEFAULT_ON = {evaluate.RULES_ONLY, evaluate.SETUPS[1]}
EVAL_CSS = """
<style>
.st-key-run_eval button:not(:disabled),
.st-key-run_eval button:not(:disabled):hover,
.st-key-run_eval button:not(:disabled):focus,
.st-key-run_eval button:not(:disabled):active {
    background-color: #2F6FDE;
    color: #FFFFFF;
    border: none;
    font-weight: 700;
    box-shadow: none;
}
</style>
"""


def show_eval(log_problem, notice, browse_folder) -> None:
    """log_problem, notice and browse_folder come from app.py so messages look the same."""
    st.markdown(EVAL_CSS, unsafe_allow_html=True)
    st.markdown(
        '<h1 class="app-title">Eval</h1>'
        '<p class="app-tagline">Grade the sorter against an answer key. Nothing in the folder moves.</p>',
        unsafe_allow_html=True,
    )
    running = bool(st.session_state.get("eval_running"))
    folder = st.session_state.setdefault("eval_folder", TEST_FOLDER)
    st.session_state.setdefault("eval_labels", str(Path(folder).parent / "labels.csv"))
    if st.button("Browse…", key="eval_browse", disabled=running):
        try:
            chosen = browse_folder(folder)
        except Exception as err:
            log_problem("The folder window failed.", err)
            notice("error", "The folder window couldn't be opened.")
            chosen = ""
        if chosen and chosen != folder:
            st.session_state.eval_folder = chosen
            st.session_state.eval_labels = str(Path(chosen).parent / "labels.csv")
            st.rerun()
    st.markdown(f'<p class="folder-path">{html.escape(folder)}</p>', unsafe_allow_html=True)
    st.text_input("Labels file", key="eval_labels", disabled=running)

    st.markdown("**Setups**")
    chosen_setups = []
    for index, setup in enumerate(evaluate.SETUPS):
        if st.checkbox(setup, value=setup in DEFAULT_ON, key=f"eval_setup_{index}", disabled=running):
            chosen_setups.append(setup)
    prompt = st.radio("Prompt", list(PROMPTS), horizontal=True, key="eval_prompt", disabled=running)
    st.caption(
        "With reason: the model explains each choice. "
        "Without reason: it only names the folder. Both compares the two."
    )

    if st.button("Run eval", key="run_eval", disabled=running or not chosen_setups):
        # Run on the next pass, with every control disabled, so a click can't restart it halfway.
        st.session_state.eval_running = True
        st.session_state.pop("eval_results", None)
        st.session_state.pop("eval_note", None)
        st.rerun()
    if running:
        run_now(chosen_setups, PROMPTS[prompt], log_problem)
        return
    note = st.session_state.get("eval_note")
    if note:
        notice("warning", note, clear="eval_note")
    results = st.session_state.get("eval_results")
    if results:
        show_results(results, log_problem, notice)


def run_now(setups, with_reason, log_problem) -> None:
    bar = st.progress(0.0, text="Loading the model…")

    def progress(setup: str, done: int, total: int) -> None:
        if total <= 0:
            bar.progress(0.0, text=f"{setup}: no files to grade")
            return
        # done=0 means the setup is still loading the model.
        if done == 0:
            bar.progress(0.0, text=f"{setup}: loading…")
            return
        bar.progress(done / total, text=f"{setup}: {done} of {total} files")

    try:
        assert_readable(Path(st.session_state.eval_folder))
        results = evaluate.run_eval(
            st.session_state.eval_folder,
            st.session_state.eval_labels,
            setups,
            with_reason,
            progress=progress,
        )
        if not results["folder_unchanged"]:
            log_problem("Folder changed during eval:\n" + "\n".join(results["folder_changes"]))
        st.session_state.eval_results = results
    except ValueError as err:
        log_problem("Eval stopped.", err)
        st.session_state.eval_note = str(err)
    except OSError as err:
        log_problem("Eval could not read the folder or labels.", err)
        st.session_state.eval_note = "The folder or labels file couldn't be read."
    except Exception as err:
        if err.__class__.__name__ in {"RerunException", "StopException"}:
            raise
        log_problem("Eval failed.", err)
        st.session_state.eval_note = "The eval couldn't finish. Please try again."
    finally:
        st.session_state.eval_running = False
    st.rerun()


def show_results(results: dict, log_problem, notice) -> None:
    if results["folder_unchanged"]:
        st.markdown('<p class="done-bar">✓ Folder unchanged</p>', unsafe_allow_html=True)
    else:
        notice("error", "The folder changed while the eval ran. Details are in app.log.")
    for text in results["skipped"] + results["warnings"]:
        notice("info", text)
    if not results["runs"]:
        notice("info", "Nothing ran. Pick at least one setup that can run.")
        return
    if results["sorted_count"] == 0:
        notice("info", "No non-duplicate labeled files to grade.")
    st.caption(
        "Prompt: (reason) = model explains in ≤10 words then picks a folder. "
        "(no reason) = folder only. Rules only never asks the model."
    )
    st.markdown(comparison_markdown(results["runs"]))
    show_chart(results["runs"])
    st.markdown(
        evaluate.slice_table(
            "AI accuracy by category (AI-decided files only)",
            results["runs"],
            "by_category",
            ["Receipts", "School", "Work", "Other", "Screenshots", "Installers", "Archives", "Photos"],
        )
    )
    st.markdown(
        evaluate.slice_table(
            "AI accuracy by difficulty (AI-decided files only)",
            results["runs"],
            "by_difficulty",
            ["clear", "edge", "normal"],
        )
    )
    st.markdown(f"**{evaluate.duplicate_line(results)}** The scanner finds copies, so this is the same for every setup.")
    show_mistakes(results)
    show_download(results, log_problem)


def comparison_markdown(runs: list[dict]) -> str:
    best = max(run["accuracy"] for run in runs)
    fewest = min(run["wrong"] for run in runs)
    lines = [
        "| Setup | Prompt | Correct | Review | Wrong moves | Accuracy % | AI correct / AI files "
        "| Sec per AI file | Total time |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for run in runs:
        accuracy = bold(f"{run['accuracy']}", run["accuracy"] == best)
        wrong = bold(f"{run['wrong']}", run["wrong"] == fewest)
        lines.append(
            f"| {run['setup']} | {run['prompt']} | {run['correct']} | {run['review']} | {wrong} "
            f"| {accuracy} | {run['ai_correct']} / {run['ai_files']} "
            f"| {run['seconds_per_ai_file']} s | {run['total_seconds']} s |"
        )
    return "\n".join(lines)


def bold(text: str, on: bool) -> str:
    return f"**{text}**" if on else text


def show_chart(runs: list[dict]) -> None:
    data = pd.DataFrame(
        {
            "Correct": [run["correct"] for run in runs],
            "Review": [run["review"] for run in runs],
            "Wrong moves": [run["wrong"] for run in runs],
        },
        index=[run["name"] for run in runs],
    )
    st.bar_chart(data, stack=False, color=["#2F6FDE", "#B8B8B8", "#1A1A1A"], horizontal=True)


def show_mistakes(results: dict) -> None:
    names = [run["name"] for run in results["runs"]]
    # Duplicate rows have no sorting answer; they only matter for the duplicate score.
    rows = [row for row in results["rows"] if row["is_duplicate"] != "yes"]
    if st.toggle("Only files someone got wrong", value=True, key="eval_only_wrong"):
        rows = [row for row in rows if any(answer_for(row, name) != row["true_label"] for name in names)]
    if not rows:
        st.caption("Every setup got every file right.")
        return
    table = pd.DataFrame(
        [
            {
                "File": row["file"],
                "True label": row["true_label"],
                "Why true": row.get("why_true", ""),
                **{name: answer_for(row, name) for name in names},
            }
            for row in rows
        ]
    )
    styled = color_wrong_answers(table, names)
    picked = st.dataframe(
        styled,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="eval_mistakes",
    )
    selected = picked.selection.rows if picked else []
    if not selected or selected[0] >= len(rows):
        st.caption("Wrong answers are light red. Click a file to see each setup's reason.")
        return
    row = rows[selected[0]]
    lines = [
        f"**{row['file']}** (true label: {row['true_label']} — {row.get('why_true', '')})"
    ]
    for name in names:
        answer = row["answers"].get(name) or {}
        lines.append(
            f"- {name}: {answer.get('answer', '')} ({answer.get('source', '')}: {answer.get('reason', '')})"
        )
    st.markdown("\n".join(lines))


def color_wrong_answers(table: pd.DataFrame, setup_names: list[str]):
    """Paint a cell light red when that setup's answer differs from True label."""

    def paint(column: pd.Series) -> list[str]:
        if column.name not in setup_names:
            return [""] * len(column)
        styles = []
        for value, truth in zip(column, table["True label"]):
            if value != "" and value != truth:
                styles.append("background-color: #F8D7DA; color: #1A1A1A")
            else:
                styles.append("")
        return styles

    return table.style.apply(paint, axis=0)


def answer_for(row: dict, name: str) -> str:
    return (row["answers"].get(name) or {}).get("answer", "")


def show_download(results: dict, log_problem) -> None:
    path = Path(results.get("csv_path") or "")
    stamp = results.get("run_id") or path.stem.replace("results_", "", 1) or "results"
    name = f"results_{stamp}.csv"
    try:
        data = path.read_bytes()
    except OSError as err:
        # The eval already finished; still offer the same CSV from memory.
        log_problem("Could not read the eval results file; offering it from memory.", err)
        data = evaluate.csv_text(results).encode("utf-8")
    st.download_button("Download results", data, file_name=name, mime="text/csv", key="eval_download")
