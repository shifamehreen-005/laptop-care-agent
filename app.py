"""Laptop Care window. Scan, approve, then move. Nothing moves before Approve."""

import copy
import importlib
import hashlib
import html
import json
import logging
import os
import re
import stat
import subprocess
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import streamlit as st

import ask_agent
import classifier
import eval_view
import executor
import folders
import health
import safety
import scanner
from config import ASK_MODEL, DEFAULT_MODEL, LARGE_FILE_MB, MODELS, TEST_FOLDER
from planner import DUPLICATE_FOLDER, build_plan


# Windows file attributes. Online-only OneDrive files must not be opened.
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
SKIP_BITS = (
    FILE_ATTRIBUTE_HIDDEN
    | FILE_ATTRIBUTE_SYSTEM
    | FILE_ATTRIBUTE_OFFLINE
    | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)
MAX_FILES = 2000
LAST_FOLDER = Path(__file__).resolve().with_name("last_folder.txt")
APP_LOG = Path(__file__).resolve().with_name("app.log")
TOO_MANY = "This folder has more than 2,000 files, so the scan stopped."
AI_OFF = "AI is off (Ollama isn't running). Unclear files go to Review."


class ScanStop(Exception):
    """Stop a scan with a message that is safe to show."""

    def __init__(self, message: str, warning: bool = False) -> None:
        super().__init__(message)
        self.warning = warning


def log_problem(summary: str, err: BaseException | None = None) -> None:
    """Write the real failure to app.log. The screen only gets a short sentence."""
    try:
        logger = logging.getLogger("laptop-care")
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            handler = logging.FileHandler(APP_LOG, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
            logger.propagate = False
        if err is None:
            logger.error("%s", summary)
            return
        details = "".join(traceback.format_exception(err))
        logger.error("%s\n%s", summary, details)
    except OSError:
        return


def notice(kind: str, text: str, clear: str = "", stay_closed: bool = False) -> None:
    """A message bar with a ✕. clear names the saved note to forget on close."""
    closed = st.session_state.setdefault("closed_notes", set())
    if text in closed:
        return
    key = widget_key("note", f"{kind}:{text}")
    with st.container(key=f"note_box_{key}", horizontal=True, vertical_alignment="center", gap="small"):
        getattr(st, kind)(text)
        if st.button("✕", key=f"note_x_{key}", help="Close"):
            if clear:
                st.session_state.pop(clear, None)
            # Warnings worked out on every run would come straight back without this.
            if stay_closed:
                closed.add(text)
            st.rerun()


def main() -> None:
    # Streamlit reloads this file and can keep an older executor in memory.
    importlib.reload(executor)
    st.set_page_config(layout="wide", page_title="Laptop Care Agent")
    try:
        inject_css()
        mode = st.sidebar.radio(
            "Mode", ["Tidy", "Eval"], key="mode", disabled=bool(st.session_state.get("eval_running"))
        )
        if mode == "Eval":
            # The eval loads and unloads each model itself, so no warm-up here.
            eval_view.show_eval(log_problem, notice, browse_folder)
            return
        warm_model()
        if not st.session_state.get("folder"):
            st.session_state.folder = load_folder()
        screen = st.session_state.get("screen", "start")
        if screen != "plan":
            # The last screen stays faded on the page until this run ends.
            # The plan screen keeps it, so its cards don't flicker on every click.
            st.markdown(
                '<style>[data-stale="true"] { display: none !important; }</style>',
                unsafe_allow_html=True,
            )
        if screen == "plan":
            show_plan()
        elif screen == "report":
            st.title("Laptop Care Agent")
            st.markdown('<p class="done-bar">Done! Files organized.</p>', unsafe_allow_html=True)
            show_undo(return_start=True)
            show_report()
            show_hold_copies()
            show_disk()
            show_battery()
        else:
            show_start()
    except Exception as err:
        # st.rerun() uses an exception. That one has to keep going.
        if err.__class__.__name__ in {"RerunException", "StopException"}:
            raise
        log_problem("The screen failed.", err)
        notice("error", "Something went wrong. Please try again.")


def inject_css() -> None:
    st.markdown(
        """
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;700&display=swap">
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;700&display=swap');
        .stApp, .stApp h1, .stApp h2, .stApp h3, .stApp p, .stApp label,
        .stApp li, .stApp input, .stApp textarea, .stApp button,
        .app-title, .app-tagline, .folder-path, .skipped-list {
            font-family: "DM Sans", "Segoe UI", sans-serif;
        }
        .stApp .app-title {
            font-weight: 700;
            font-size: 2.75rem;
            line-height: 1.15;
            color: #1A1A1A;
            margin: 0 0 0.25rem 0;
        }
        .app-tagline {
            font-size: 1.05rem;
            color: #1A1A1A;
            margin: 0 0 1.25rem 0;
        }
        .folder-path {
            color: #1A1A1A;
            background: #FFFFFF;
            border: 1px solid #E5E5E5;
            border-radius: 8px;
            padding: 8px 12px;
            margin: 8px 0 16px 0;
            word-break: break-all;
        }
        .skipped-list {
            color: #1A1A1A;
            margin: 0 0 1rem 0;
            word-break: break-all;
        }
        .st-key-understand [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type {
            background-color: #1B8A4A;
            border-color: #1B8A4A;
            color: #FFFFFF;
        }
        .st-key-understand [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type svg,
        .st-key-understand [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type polyline,
        .st-key-understand [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type path {
            stroke: #FFFFFF;
            color: #FFFFFF;
        }
        .st-key-use_ai [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type {
            background-color: #1B8A4A;
            border-color: #1B8A4A;
        }
        .st-key-use_ai [data-testid="stCheckbox"] label > div:not(:first-of-type),
        .st-key-understand [data-testid="stCheckbox"] label > div:not(:first-of-type) {
            background: transparent;
        }
        .st-key-scan button:not(:disabled),
        .st-key-scan button:not(:disabled):hover,
        .st-key-scan button:not(:disabled):focus,
        .st-key-scan button:not(:disabled):active {
            background-color: #2F6FDE;
            color: #FFFFFF;
            border: none;
            font-weight: 700;
            box-shadow: none;
        }
        .st-key-choices {
            width: fit-content;
            margin-bottom: 4px;
        }
        .st-key-approve button,
        .st-key-approve button:hover,
        .st-key-approve button:focus,
        .st-key-approve button:active {
            background-color: #2F6FDE;
            color: #FFFFFF;
            border: none;
            font-weight: 700;
            box-shadow: none;
        }
        .st-key-no button,
        .st-key-no button:hover,
        .st-key-no button:focus,
        .st-key-no button:active,
        .st-key-cancel button,
        .st-key-cancel button:hover,
        .st-key-cancel button:focus,
        .st-key-cancel button:active,
        .st-key-save_labels button,
        .st-key-save_labels button:hover,
        .st-key-save_labels button:focus,
        .st-key-save_labels button:active {
            background-color: #FFFFFF;
            color: #1A1A1A;
            border: 1px solid #D0D0D0;
            box-shadow: none;
        }
        .st-key-undo_review button,
        .st-key-undo_review button:hover,
        .st-key-undo_review button:focus,
        .st-key-undo_review button:active,
        .st-key-undo_review button:disabled {
            background: #F1F1F1;
            color: #1A1A1A;
            border: none;
            border-radius: 999px;
            font-weight: 700;
            box-shadow: none;
        }
        .st-key-undo_review button:disabled {
            color: #8A8A8A;
        }
        .done-bar {
            background: rgba(27, 138, 74, 0.12);
            color: #145C32;
            font-weight: 600;
            font-size: 1.05rem;
            border: 1px solid rgba(27, 138, 74, 0.35);
            border-radius: 10px;
            padding: 12px 16px;
            margin: 4px 0 12px 0;
        }
        .st-key-undo_done button,
        .st-key-undo_done button:focus,
        .st-key-undo_done button:active {
            background: rgba(47, 111, 222, 0.12);
            color: #1A1A1A;
            border: 2px solid #2F6FDE;
            border-radius: 8px;
            font-weight: 600;
            width: fit-content;
            box-shadow: none;
        }
        .st-key-undo_done button:hover {
            background: rgba(47, 111, 222, 0.2);
            color: #1A1A1A;
            border: 2px solid #2F6FDE;
        }
        .st-key-undo_done button:disabled {
            background: rgba(47, 111, 222, 0.06);
            color: #8A8A8A;
            border: 2px solid #D0D0D0;
        }
        [class*="st-key-note_box_"] {
            flex-wrap: nowrap;
        }
        [class*="st-key-note_box_"] > div:first-child {
            flex: 1 1 auto;
            min-width: 0;
        }
        [class*="st-key-note_x_"] button {
            background: transparent;
            border: none;
            color: #6B6B6B;
            min-height: 0;
            padding: 0.2rem 0.5rem;
        }
        [class*="st-key-note_x_"] button:hover {
            background: rgba(47, 111, 222, 0.12);
            color: #2F6FDE;
        }
        .stApp .st-key-reset_review button,
        .stApp .st-key-reset_review button:hover,
        .stApp .st-key-reset_review button:focus,
        .stApp .st-key-reset_review button:active {
            background: transparent;
            color: #1A1A1A;
            border: none;
            box-shadow: none;
            font-weight: 700;
            text-decoration: underline;
            text-underline-offset: 3px;
        }
        .stApp .st-key-reset_review button:disabled {
            color: #8A8A8A;
            text-decoration: none;
        }
        div[class*="st-key-chip_"] {
            width: fit-content;
            display: inline-block;
            margin: 0 6px 6px 0;
        }
        div[class*="st-key-chip_"] button {
            background: #F1F1F1;
            color: #1A1A1A;
            border: none;
            border-radius: 999px;
            font-weight: 400;
            min-height: 0;
            padding: 2px 12px;
        }
        div[class*="st-key-pen_"],
        div[class*="st-key-remove_"] {
            width: fit-content;
        }
        div[class*="st-key-pen_"] {
            margin-left: 6px;
        }
        div[class*="st-key-pen_"] button,
        div[class*="st-key-pen_"] button:hover,
        div[class*="st-key-pen_"] button:focus,
        div[class*="st-key-pen_"] button:active {
            background: transparent;
            color: #1A1A1A;
            border: none;
            outline: none;
            box-shadow: none;
            height: 24px;
            min-height: 24px;
            line-height: 1;
            padding: 0 2px;
        }
        div[class*="st-key-remove_"] button {
            background: #FFFFFF;
            color: #1A1A1A;
            border: 1px solid #D0D0D0;
            box-shadow: none;
            min-height: 0;
            padding: 2px 10px;
        }
        .file-nav {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 2px;
            background: #FFFFFF;
            border: 1px solid #E5E5E5;
            border-radius: 10px;
            padding: 6px 10px;
            margin: 4px 0 12px 0;
        }
        .nav-tab {
            background: transparent;
            color: #6B6B6B;
            border: none;
            border-bottom: 2px solid transparent;
            border-radius: 0;
            font-family: "DM Sans", "Segoe UI", sans-serif;
            padding: 6px 12px;
            cursor: pointer;
        }
        .nav-word {
            font-weight: 700;
            font-size: 17px;
        }
        .nav-count {
            font-weight: 400;
            font-size: 12px;
            color: #6B6B6B;
            margin-left: 6px;
        }
        .nav-on {
            color: #1A1A1A;
            border-bottom-color: #1A1A1A;
        }
        .nav-on .nav-word {
            color: #1A1A1A;
        }
        .nav-mode {
            margin-left: auto;
            color: #6B6B6B;
            font-size: 14px;
            white-space: nowrap;
            padding-left: 16px;
        }
        div[data-testid="stMetric"] {
            background: #FFFFFF;
            border: 1px solid #E5E5E5;
            border-radius: 12px;
            padding: 12px 16px;
            box-shadow: none;
        }
        div[data-testid="stMetric"] label {
            color: #6B6B6B;
        }
        div[data-testid="stMetricValue"] {
            color: #1A1A1A;
        }
        div[class*="st-key-card_"] {
            background: #FFFFFF;
            border: 1px solid #E5E5E5;
            border-radius: 12px;
            padding: 16px;
            box-shadow: none;
        }
        div[class*="st-key-card_"]:has(input:checked) {
            opacity: 0.4;
        }
        .folder-line {
            color: #6B6B6B;
            font-size: 0.95rem;
            margin: 10px 0 8px 0;
        }
        .add-heading {
            color: #1A1A1A;
            font-weight: 700;
            font-size: 1.05rem;
            margin: 0 0 4px 0;
        }
        .similar-ask {
            color: #1A1A1A;
            font-size: 0.95rem;
            margin: 8px 0;
        }
        .st-key-label_tools,
        .st-key-add_fields,
        .st-key-preview_actions {
            width: fit-content;
            max-width: 100%;
            flex-wrap: nowrap;
            align-items: center;
        }
        div[data-testid="stForm"] {
            width: fit-content;
            border: none;
            padding: 0;
        }
        div[data-testid="stForm"] [data-testid="stCaptionContainer"],
        div[data-testid="stForm"] [data-testid="InputInstructions"] {
            display: none;
        }
        div[class*="st-key-new_name"] {
            width: 220px;
        }
        div[class*="st-key-add_label_go"] {
            width: fit-content;
        }
        div[class*="st-key-add_label_go"] button,
        div[class*="st-key-add_label_go"] button:hover,
        div[class*="st-key-add_label_go"] button:focus,
        div[class*="st-key-add_label_go"] button:active {
            background: #FFFFFF;
            color: #1A1A1A;
            border: 1px solid #D0D0D0;
            box-shadow: none;
            min-height: 0;
            padding: 4px 12px;
        }
        .st-key-review_bar {
            align-items: center;
            margin-bottom: 8px;
        }
        .st-key-drop_token {
            display: none;
            height: 0;
            margin: 0;
        }
        div[class*="st-key-head-"] {
            width: 100%;
            max-width: 100%;
            flex-wrap: nowrap;
            align-items: center;
            overflow: visible;
        }
        div[class*="st-key-head-"] [data-testid="stElementContainer"] {
            height: auto;
            min-height: 24px;
            overflow: visible;
            flex: 0 0 auto;
        }
        div[class*="st-key-rename_input_"] {
            width: 180px;
        }
        div[class*="st-key-rename_input_"] input {
            color: #1A1A1A;
            font-weight: 700;
            font-size: 20px;
            background: transparent;
            border: none;
            border-bottom: 1px solid #D0D0D0;
            border-radius: 0;
            padding: 0 0 2px 0;
        }
        div[class*="st-key-card-"].drop-over {
            outline: 2px solid #2F6FDE;
            outline-offset: 2px;
        }
        div[class*="st-key-card-"],
        div[class*="st-key-pile-"],
        div[class*="st-key-suggest-"] {
            height: 320px;
            min-height: 320px;
            max-height: 320px;
            overflow: hidden;
        }
        .chip-row {
            display: flex;
            flex-wrap: wrap;
            align-content: flex-start;
            gap: 8px;
            margin-top: 8px;
            max-height: 168px;
            overflow-y: auto;
            padding-top: 8px;
            scrollbar-width: thin;
            scrollbar-color: #B0B0B0 transparent;
        }
        .chip-row::-webkit-scrollbar {
            width: 8px;
        }
        .chip-row::-webkit-scrollbar-thumb {
            background: #B0B0B0;
            border-radius: 8px;
        }
        .chip-wrap {
            position: relative;
            display: inline-flex;
            max-width: 100%;
        }
        .moved-flag {
            position: absolute;
            z-index: 2;
            top: -7px;
            left: 10px;
            background: #FFFFFF;
            color: #1A1A1A;
            border: 1px solid #1A1A1A;
            border-radius: 4px;
            font-family: "DM Sans", "Segoe UI", sans-serif;
            font-size: 10px;
            font-weight: 700;
            line-height: 1.2;
            padding: 1px 5px;
            pointer-events: none;
        }
        .file-chip {
            appearance: none;
            background: #F1F1F1;
            color: #1A1A1A;
            border: 2px solid transparent;
            border-radius: 999px;
            font-weight: 400;
            font-family: "DM Sans", "Segoe UI", sans-serif;
            font-size: 13px;
            line-height: 1.2;
            padding: 3px 12px;
            margin: 2px 0;
            cursor: grab;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .file-chip:focus,
        .file-chip:focus-visible {
            outline: none;
        }
        .file-chip-on {
            border-color: #2F6FDE;
        }
        .ai-tag {
            color: #2F6FDE;
            font-weight: 700;
            margin-left: 8px;
        }
        .preview-title {
            color: #1A1A1A;
            font-weight: 700;
            font-size: 1.15rem;
            margin: 0;
            text-align: center;
        }
        div[class*="st-key-preview_head"] {
            width: 100%;
            flex-wrap: nowrap;
            justify-content: center;
            align-items: center;
            gap: 8px;
        }
        div[class*="st-key-preview_head"] [data-testid="stElementContainer"] {
            width: auto;
            height: auto;
            flex: 0 0 auto;
            overflow: visible;
        }
        div[class*="st-key-clear_preview"] {
            width: fit-content;
        }
        div[class*="st-key-clear_preview"] button,
        div[class*="st-key-clear_preview"] button:hover,
        div[class*="st-key-clear_preview"] button:focus,
        div[class*="st-key-clear_preview"] button:active {
            background: transparent;
            color: #1A1A1A;
            border: none;
            outline: none;
            box-shadow: none;
            height: 24px;
            min-height: 24px;
            line-height: 1;
            padding: 0 2px;
            font-size: 20px;
        }
        .cat-head {
            display: flex;
            align-items: baseline;
            gap: 8px;
            margin: 0;
        }
        .cat-name {
            color: #1A1A1A;
            font-size: 20px;
            font-weight: 700;
            line-height: 1.2;
            white-space: nowrap;
        }
        .cat-count {
            color: #6B6B6B;
            font-size: 13px;
            font-weight: 400;
            line-height: 1.2;
        }
        .field-label {
            color: #1A1A1A;
            font-weight: 700;
            font-size: 0.95rem;
            margin: 28px 0 4px 0;
        }
        .field-value {
            color: #1A1A1A;
            font-weight: 400;
            font-size: 0.95rem;
            margin: 0;
            word-break: break-word;
        }
        .last-location {
            color: #6B6B6B;
            font-size: 0.9rem;
            margin: 16px 0 0 0;
        }
        .move-gap {
            height: 28px;
        }
        div[class*="st-key-preview_pane"] [data-testid="stSelectbox"] {
            margin-top: 0;
        }
        div[class*="st-key-preview_pane"] [data-testid="stSelectbox"] label {
            margin-top: 4px;
            margin-bottom: 4px;
        }
        div[class*="st-key-preview_pane"] .st-key-preview_actions {
            margin-top: 20px;
        }
        div[class*="st-key-preview_pane"] .st-key-open_file,
        div[class*="st-key-preview_pane"] .st-key-show_folder {
            width: fit-content;
            margin-top: 0;
        }
        div[class*="st-key-cat_"] {
            display: flex;
            justify-content: flex-end;
        }
        div[class*="st-key-cat_"] label {
            color: #6B6B6B;
            font-size: 14px;
            white-space: nowrap;
        }
        .stay {
            color: #6B6B6B;
            font-size: 14px;
            margin: 8px 0 0;
        }
        .chips {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 8px 0 0;
        }
        .chip {
            display: inline-flex;
            align-items: center;
            max-width: 220px;
            background: #F1F1F1;
            color: #1A1A1A;
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 13px;
            line-height: 1.3;
        }
        .chip-name {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            min-width: 0;
        }
        .ai-badge {
            flex: none;
            color: #6B6B6B;
            background: transparent;
            border: 1px solid #6B6B6B;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 600;
            padding: 0 5px;
            margin-left: 6px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def warm_model() -> None:
    # One small request loads llama into memory. Later calls keep it for 30 minutes.
    if st.session_state.get("warmed"):
        note = st.session_state.get("warmup_note")
        if note:
            st.caption(note)
        return
    with st.spinner("Starting the local model..."):
        st.session_state.warmup_note = ask_ollama("OK")
    st.session_state.warmed = True
    if st.session_state.warmup_note:
        st.caption(st.session_state.warmup_note)


def ask_ollama(prompt: str) -> str | None:
    body = json.dumps(
        {
            "model": classifier.MODEL,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "30m",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        classifier.OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=classifier.TIMEOUT_SECONDS) as response:
            response.read()
    except (OSError, urllib.error.URLError, TimeoutError):
        return "Ollama did not answer. Rules still work."
    return None


def close_delete_ask() -> None:
    st.session_state.hold_ask = False


@st.dialog("Delete files", on_dismiss=close_delete_ask)
def delete_dialog() -> None:
    st.write("Delete the whole Safe to remove folder?")
    with st.container(horizontal=True, gap="small"):
        yes = st.button("Yes", key="delete_yes", type="primary")
        no = st.button("No", key="delete_no")
    if no:
        st.session_state.hold_ask = False
        st.rerun()
    if yes:
        # Close the popup first. The page does the work and shows Working.
        st.session_state.hold_ask = False
        st.session_state.working = "delete"
        st.rerun()


def close_undo_ask() -> None:
    st.session_state.undo_ask = False


@st.dialog("Undo", on_dismiss=close_undo_ask)
def undo_dialog() -> None:
    st.write("Put every file back where it was before Approve?")
    with st.container(horizontal=True, gap="small"):
        yes = st.button("Yes", key="undo_yes", type="primary")
        no = st.button("No", key="undo_no")
    if no:
        st.session_state.undo_ask = False
        st.rerun()
    if yes:
        st.session_state.undo_ask = False
        st.session_state.working = "undo"
        st.rerun()


def undo_now() -> None:
    try:
        executor.undo_approval(st.session_state.run_id, executor.log_path_for_folder())
    except Exception as err:
        log_problem("Undo failed.", err)
        notice("error", "Those files couldn't be put back.")
        return
    st.session_state.run_id = None
    st.session_state.hold_note = ""
    st.session_state.hold_ask = False
    st.session_state.undo_note = "Undone. Files are back."
    st.session_state.screen = "start"
    st.rerun()


def show_undo(ask_home: bool = False, return_start: bool = False) -> None:
    """On the done screen, go back to how the folder was before Approve."""
    if return_start:
        st.write("Put every file back?")
        run_id = st.session_state.get("run_id")
        if st.button("Undo", key="undo_done", disabled=not run_id):
            # Streamlit shows one dialog at a time.
            st.session_state.hold_ask = False
            st.session_state.undo_ask = True
            st.rerun()
        # The spinner takes the popup's place on the page, so the popup closes at once.
        if st.session_state.get("working") == "undo" and run_id:
            st.session_state.working = ""
            with st.spinner("Working…"):
                undo_now()
        if st.session_state.get("undo_ask") and run_id:
            undo_dialog()
        return
    if st.session_state.get("ask_home"):
        notice("success", "Undone. Files are back.")
        st.write("Go back to the home page?")
        with st.container(horizontal=True, gap="small"):
            if st.button("Yes", key="home_yes"):
                st.session_state.ask_home = False
                st.session_state.undo_note = ""
                st.session_state.screen = "start"
                st.rerun()
            if st.button("No", key="home_no"):
                st.session_state.ask_home = False
                st.rerun()
        return
    if not st.session_state.get("run_id"):
        if st.session_state.get("undo_note"):
            notice("success", st.session_state.undo_note, clear="undo_note")
        return
    if st.button("Undo", key="undo_disk"):
        try:
            executor.undo(st.session_state.run_id, executor.log_path_for_folder())
        except Exception as err:
            log_problem("Undo failed.", err)
            notice("error", "Those files couldn't be put back.")
            return
        st.session_state.run_id = None
        st.session_state.undo_note = "Undone. Files are back."
        if ask_home:
            st.session_state.ask_home = True
        st.rerun()
    if st.session_state.get("undo_note"):
        notice("success", st.session_state.undo_note, clear="undo_note")


def show_start() -> None:
    st.markdown(
        '<h1 class="app-title">Laptop Care Agent</h1>'
        '<p class="app-tagline">Tidy a folder safely. Nothing moves until you approve.</p>',
        unsafe_allow_html=True,
    )
    show_undo()
    folder = st.session_state.folder
    if st.button("Browse…"):
        try:
            chosen = browse_folder(folder)
        except Exception as err:
            log_problem("The folder window failed.", err)
            notice("error", "The folder window couldn't be opened.")
            chosen = ""
        if chosen:
            if chosen != folder:
                st.session_state.understand = False
            st.session_state.folder = chosen
            remember_folder(chosen)
            st.rerun()
    st.markdown(
        f'<p class="folder-path">{html.escape(st.session_state.folder)}</p>',
        unsafe_allow_html=True,
    )
    ok, reason = safety.is_allowed_folder(st.session_state.folder)
    if not ok:
        notice("warning", reason, stay_closed=True)
    real = ok and not is_test_folder(st.session_state.folder)
    if real:
        notice(
            "warning",
            "Warning: This is a real folder. Nothing moves until you approve, "
            "and Undo can put everything back.",
            stay_closed=True,
        )
        understood = st.checkbox("I understand", key="understand")
    else:
        understood = True
    st.toggle("Use AI for unclear files", value=True, key="use_ai")
    st.selectbox("Model", MODELS, index=MODELS.index(DEFAULT_MODEL), key="scan_model")
    st.toggle(
        "Ask an agent",
        value=bool(st.session_state.get("ask_agent", False)),
        key="ask_agent",
        help="The scan stays the same. A question after that uses qwen2.5:3b.",
    )
    if st.session_state.get("ask_agent"):
        st.caption("The scan is unchanged. Ask a question and qwen2.5:3b sorts from that.")
    if st.button("Scan", key="scan", disabled=not (ok and understood)):
        run_scan(
            st.session_state.folder,
            bool(st.session_state.get("use_ai", True)),
            ask_on=bool(st.session_state.get("ask_agent")),
            model=st.session_state.get("scan_model") or DEFAULT_MODEL,
        )


def load_folder() -> str:
    try:
        if LAST_FOLDER.is_file():
            saved = LAST_FOLDER.read_text(encoding="utf-8").strip()
            if saved:
                return saved
    except OSError as err:
        log_problem("Could not read the last folder.", err)
    return TEST_FOLDER


def remember_folder(folder: str) -> None:
    try:
        LAST_FOLDER.write_text(folder, encoding="utf-8")
    except OSError as err:
        log_problem("Could not remember the folder.", err)


def browse_folder(current: str) -> str:
    """Open the Windows folder window on top of the browser."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    try:
        root.withdraw()
        # Without topmost, the dialog opens behind the browser window.
        root.attributes("-topmost", True)
        root.update()
        start_in = current if current and Path(current).is_dir() else str(Path.home())
        chosen = filedialog.askdirectory(parent=root, initialdir=start_in)
    finally:
        root.destroy()
    if not chosen:
        return ""
    return str(Path(chosen))


def is_test_folder(folder: str) -> bool:
    if not folder or not str(folder).strip():
        return False
    try:
        return Path(folder).expanduser().resolve() == Path(TEST_FOLDER).expanduser().resolve()
    except OSError:
        return False


def run_scan(folder: str, use_ai: bool, ask_on: bool = False, model: str = "") -> None:
    st.session_state.ai_note = ""
    st.session_state.skipped = []
    st.session_state.ask_note = ""
    started = time.perf_counter()
    try:
        with st.spinner("Scanning..."):
            # One model in memory. A leftover Qwen makes a normal scan wait.
            # Ask an agent does not sort during the scan. It waits for a question.
            if use_ai:
                keep_only(model or DEFAULT_MODEL)
            else:
                keep_only("")
            files, skipped, disk_folders = collect_scan(folder)
            ai_note = ""
            if use_ai and not ollama_running():
                use_ai = False
                ai_note = AI_OFF
            plan = build_plan(files, use_ai=use_ai, model=model or DEFAULT_MODEL)
            labels = load_review_labels()
            suggestions = prepare_review(files, plan, labels, use_ai, disk_folders)
            ask_note = ""
    except ScanStop as err:
        if err.warning:
            notice("warning", str(err))
        else:
            notice("error", str(err))
        return
    except Exception as err:
        log_problem("Scan failed.", err)
        notice("error", "That folder couldn't be scanned.")
        return
    remember_folder(folder)
    st.session_state.files = files
    st.session_state.plan = plan
    st.session_state.labels = labels
    st.session_state.suggestions = suggestions
    if use_ai:
        st.session_state.scan_mode = f"Rules + {model or DEFAULT_MODEL}"
    else:
        st.session_state.scan_mode = "Rules only"
    st.session_state.ask_mode = ask_on
    st.session_state.selected = ""
    st.session_state.skipped = skipped
    st.session_state.ai_note = ai_note
    st.session_state.ask_note = ask_note
    st.session_state.duplicates_found = sum(1 for item in files if item.get("is_duplicate"))
    st.session_state.large_found = sum(
        1 for item in files if (item.get("size_bytes") or 0) > LARGE_FILE_MB * 1_048_576
    )
    st.session_state.scan_seconds = time.perf_counter() - started
    st.session_state.screen = "plan"
    st.session_state.undo_note = ""
    st.session_state.labels_dirty = False
    st.session_state.save_note = ""
    st.session_state.file_view = "files"
    st.session_state.undo_stack = []
    st.session_state.show_create = False
    st.session_state.label_note = ""
    st.session_state.pending_label = ""
    st.session_state.pending_note = ""
    st.session_state.original_review = {
        "plan": copy.deepcopy(plan),
        "labels": copy.deepcopy(labels),
        "suggestions": copy.deepcopy(suggestions),
    }
    clear_choices()
    st.rerun()


def collect_scan(path: str) -> tuple[list[dict], list[str], list[str]]:
    """List every file under the chosen folder, then open only the safe ones.

    Hidden, system, and online-only files are not opened. More than 2,000 files
    stops the scan before any file contents are read. The third value is every
    folder found, including empty ones.
    """
    folder = Path(path).expanduser().resolve()
    readable: list[tuple[Path, str]] = []
    problems: list[tuple[str, BaseException]] = []
    seen = 0
    for directory, folder_name in scan_dirs(folder):
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name.lower())
        except OSError as err:
            log_problem(f"Could not list {directory}", err)
            if directory == folder:
                raise ScanStop("That folder couldn't be scanned.") from err
            continue
        for item in entries:
            try:
                info = item.stat()
            except OSError as err:
                seen += 1
                if seen > MAX_FILES:
                    log_problem(TOO_MANY)
                    raise ScanStop(TOO_MANY, warning=True) from err
                problems.append((skipped_name(folder_name, item.name), err))
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            seen += 1
            if seen > MAX_FILES:
                log_problem(TOO_MANY)
                raise ScanStop(TOO_MANY, warning=True)
            attrs = getattr(info, "st_file_attributes", 0) or 0
            if attrs & SKIP_BITS:
                continue
            readable.append((item, folder_name))
    skipped = []
    for label, err in problems:
        log_problem(f"Skipped {label}", err)
        skipped.append(label)
    files = []
    for item, folder_name in readable:
        record = scanner.describe_file(folder, item, folder_name)
        if record.get("sha256"):
            files.append(record)
            continue
        label = skipped_name(folder_name, item.name)
        log_problem(f"Skipped {label}: {record.get('error') or 'could not open'}")
        skipped.append(label)
    scanner.mark_duplicates(files)
    disk_folders = [name for _directory, name in scan_dirs(folder) if name]
    return files, skipped, disk_folders


def scan_dirs(folder: Path) -> list[tuple[Path, str]]:
    found = [(folder, "")]
    for name in scanner.folders_to_read(folder):
        sub = folder / name
        if not scanner.stays_in(folder, sub):
            continue
        try:
            if not sub.is_dir():
                continue
            info = sub.stat()
        except OSError as err:
            log_problem(f"Could not open folder {name}", err)
            continue
        attrs = getattr(info, "st_file_attributes", 0) or 0
        if attrs & SKIP_BITS:
            continue
        found.append((sub, name))
    return found


def skipped_name(folder_name: str, name: str) -> str:
    if folder_name:
        return f"{folder_name}/{name}"
    return name


def ollama_running() -> bool:
    request = urllib.request.Request("http://127.0.0.1:11434/api/tags")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            response.read()
    except (OSError, urllib.error.URLError, TimeoutError) as err:
        log_problem("Ollama is not running.", err)
        return False
    return True


def clear_choices() -> None:
    for key in list(st.session_state):
        if key.startswith("cat_") or key.startswith("fix_") or key == "suggest":
            del st.session_state[key]


LEAVE = "Leave where it is"
NO_FOLDER = "No folder"
DUPLICATE_CHOICE = "Duplicates"
PREVIEW_LONG = 800
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}


def show_plan() -> None:
    plan = st.session_state.get("plan") or []
    files = st.session_state.get("files") or []
    take_drop()
    st.text_input("drop", key="drop_token", label_visibility="collapsed")
    install_drag()
    st.markdown('<h1 class="app-title">Laptop Care Agent</h1>', unsafe_allow_html=True)
    show_review_bar(plan)
    if st.session_state.get("ask_mode"):
        show_ask_box()
    show_file_nav(files, plan)
    show_add_row(plan)
    show_scan_notes()
    main, side = st.columns([3, 1], gap="large")
    with main:
        show_label_grid(plan)
        show_review_lists(plan)
    with side:
        show_details(plan)


def show_ask_box() -> None:
    """Ask how to sort. Samples cover type, subject, and semester."""
    st.subheader("Ask an agent")
    note = st.session_state.get("ask_note") or ""
    if note:
        st.caption(note)
    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        ask = st.text_input(
            "Ask",
            key="ask_text",
            label_visibility="collapsed",
            placeholder="How should these files be sorted?",
        )
        go = st.button("Ask", key="ask_go", type="primary")
    st.caption("Try one of these:")
    with st.container(horizontal=True, gap="small"):
        for sample in ask_agent.SAMPLES:
            if st.button(sample, key=widget_key("ask_sample", sample)):
                run_ask(sample)
                return
    if go:
        run_ask(ask)


def run_ask(ask: str) -> None:
    text = (ask or "").strip()
    if not text:
        notice("warning", "Type what you want, or tap a sample.")
        return
    remember_review()
    plan = copy.deepcopy(st.session_state.get("plan") or [])
    files = st.session_state.get("files") or []
    mode = ask_agent.pick_mode(text)
    named = None
    with st.spinner("Working…"):
        if mode == "judge":
            if not ollama_running():
                notice("warning", "Ollama isn't running. Start it, or use Group by file type.")
                return
            named = judge_names(files, plan, text)
        labels, plan, note = ask_agent.apply_ask(
            plan,
            files,
            text,
            name_for_file=(
                None
                if named is None
                else lambda record: named.get(
                    f"{record.get('folder') or ''}/{record.get('name') or ''}", ""
                )
            ),
        )
    st.session_state.labels = labels
    st.session_state.plan = plan
    st.session_state.suggestions = []
    st.session_state.ask_note = note
    st.session_state.labels_dirty = True
    clear_move_keys()
    st.rerun()


def show_review_bar(plan: list[dict]) -> None:
    with st.container(key="review_bar", horizontal=True, vertical_alignment="center", gap="small"):
        with st.container(key="choices", horizontal=True, gap="small", width="content"):
            if st.button("Approve", key="approve"):
                apply_chosen(plan)
            if st.button("Cancel", key="cancel"):
                st.session_state.screen = "start"
                st.rerun()
            can_step_back = bool(st.session_state.get("undo_stack"))
            if st.button("Undo", key="undo_review", disabled=not can_step_back):
                undo_review_change()
                st.rerun()
            if st.button("Reset", key="reset_review", disabled=not can_step_back):
                reset_to_original()
                st.rerun()
    st.caption("Nothing moves until you approve.")


def show_file_nav(files: list, plan: list[dict]) -> None:
    """Files shows everything. The other tabs show one group."""
    view = st.session_state.get("file_view") or "files"
    pending = suggested_file_ids()
    labels = st.session_state.get("labels") or []
    _, loose = review_counts(plan)
    counts = {
        "files": len(files),
        "duplicates": sum(
            1 for action in plan if action.get("destination") == DUPLICATE_FOLDER and not action.get("leave")
        ),
        "unfiled": loose,
        "large": sum(1 for action in plan if large_file(action)),
    }
    for key in ("Review", "Other"):
        label = next((item for item in labels if item.get("key") == key), None)
        if label is None:
            counts[key] = 0
            continue
        counts[key] = sum(1 for action in plan if on_label(action, label, pending))
    items = (
        ("files", "Files", counts["files"]),
        ("duplicates", "Duplicates", counts["duplicates"]),
        ("Review", "Review", counts.get("Review", 0)),
        ("Other", "Other", counts.get("Other", 0)),
        ("unfiled", "No folder", counts["unfiled"]),
        ("large", "Large files", counts["large"]),
        ("ai", "AI guesses", ai_guess_count(plan, labels)),
    )
    tabs = []
    for key, label, count in items:
        selected = " nav-on" if key == view else ""
        tabs.append(
            f'<button type="button" class="nav-tab{selected}" data-view="{html.escape(key, quote=True)}">'
            f'<span class="nav-word">{html.escape(label)}</span>'
            f'<span class="nav-count">{count}</span></button>'
        )
    mode = html.escape(st.session_state.get("scan_mode") or "Rules only")
    st.html(f'<div class="file-nav">{"".join(tabs)}<span class="nav-mode">{mode}</span></div>')


def show_add_row(plan: list[dict]) -> None:
    folders, loose = review_counts(plan)
    folder_word = "folder" if folders == 1 else "folders"
    file_word = "file" if loose == 1 else "files"
    st.markdown(
        f'<p class="folder-line">{folders} {folder_word} · {loose} {file_word} without a folder</p>',
        unsafe_allow_html=True,
    )
    open_create = bool(st.session_state.get("show_create"))
    if open_create:
        st.markdown(
            """
            <style>
            .stApp .st-key-create_label button,
            .stApp .st-key-create_label button:hover,
            .stApp .st-key-create_label button:focus,
            .stApp .st-key-create_label button:active {
                background: #FFFFFF;
                color: #2F6FDE;
                border: 2px solid #2F6FDE;
                font-weight: 700;
                box-shadow: none;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
    if st.button("Create label", key="create_label"):
        st.session_state.show_create = not open_create
        if open_create:
            st.session_state.pending_label = ""
            st.session_state.pending_note = ""
        st.rerun()
    if open_create:
        st.markdown('<p class="add-heading">Create a new label</p>', unsafe_allow_html=True)
        show_similar_ask()
        show_add_label()


def will_move(action: dict) -> bool:
    if action.get("leave") or action.get("destination") == DUPLICATE_FOLDER:
        return False
    if action.get("suggested") and not action.get("moved_by_you"):
        return False
    # A file already sitting in this folder is only shown. Approve does not move it.
    current = (action.get("folder") or "").casefold()
    destination = (action.get("destination") or "").casefold()
    if current and current == destination:
        return False
    return bool(destination)


def chosen_actions(plan: list[dict]) -> list[dict]:
    chosen = []
    for action in plan:
        if action.get("leave"):
            continue
        if action.get("suggested") and not action.get("moved_by_you"):
            continue
        if action.get("destination") == DUPLICATE_FOLDER or will_move(action):
            chosen.append(action)
    return chosen


def review_counts(plan: list[dict]) -> tuple[int, int]:
    """Folder cards, and files that are not on any named card."""
    labels = [label for label in (st.session_state.get("labels") or []) if label.get("source") != "suggested"]
    pending = suggested_file_ids()
    placed: set[str] = set()
    for label in labels:
        for action in plan:
            if on_label(action, label, pending):
                placed.add(action_id(action))
    for suggestion in st.session_state.get("suggestions") or []:
        ids = set(suggestion.get("file_ids") or [])
        matched = [
            action
            for action in plan
            if action_id(action) in ids and not action.get("moved_by_you") and not action.get("leave")
        ]
        if len(matched) < 2:
            continue
        for action in matched:
            placed.add(action_id(action))
    for action in plan:
        if action.get("destination") == DUPLICATE_FOLDER and not action.get("leave"):
            placed.add(action_id(action))
    loose = sum(1 for action in plan if action_id(action) not in placed)
    return sum(1 for label in labels if label_shown(label, plan, pending)), loose


def show_label_grid(plan: list[dict]) -> None:
    every = [label for label in (st.session_state.get("labels") or []) if label.get("source") != "suggested"]
    pending = suggested_file_ids()
    labels = [label for label in every if label_shown(label, plan, pending)]
    for label in labels:
        # Once a file goes in, the card stays even if that file leaves again.
        label.pop("hidden", None)
    cards = []
    # Other, Review, and Duplicates stay together at the end.
    end = []
    for label in labels:
        actions = [action for action in plan if on_label(action, label, pending)]
        card = ("label", label, actions)
        if label.get("key") in {"Other", "Review"}:
            end.append(card)
            continue
        cards.append(card)
    for suggestion in st.session_state.get("suggestions") or []:
        ids = set(suggestion.get("file_ids") or [])
        actions = [
            action
            for action in plan
            if action_id(action) in ids and not action.get("moved_by_you") and not action.get("leave")
        ]
        if len(actions) < 2:
            continue
        cards.append(("suggested", suggestion, actions))
    end.sort(key=lambda card: {"Other": 0, "Review": 1}.get(card[1].get("key"), 2))
    dupes = [
        action
        for action in plan
        if action.get("destination") == DUPLICATE_FOLDER and not action.get("leave")
    ]
    if dupes:
        end.append(("dupes", None, dupes))
    cards.extend(end)
    # Files with no folder stay together. The card stays up so a file can be dropped in.
    leftover = [action for action in plan if action_id(action) not in shown_ids(cards)]
    view = st.session_state.get("file_view") or "files"
    if view == "duplicates":
        cards = [card for card in cards if card[0] == "dupes"] or [("dupes", None, [])]
    elif view in {"Review", "Other"}:
        # Its own tab shows the card even when it is empty here.
        cards = [
            ("label", label, [action for action in plan if on_label(action, label, pending)])
            for label in every
            if label.get("key") == view
        ]
    elif view == "ai":
        cards = ai_guess_cards(plan, labels, pending)
        if not cards:
            st.write("No AI guesses.")
            return
    elif view == "unfiled":
        cards = [("loose", None, leftover)]
    elif view == "large":
        big = [action for action in plan if large_file(action)]
        cards = [("large", None, big)]
    elif view == "files":
        cards.append(("loose", None, leftover))
    if not cards:
        st.write("Nothing to sort.")
        return
    for start in range(0, len(cards), 3):
        columns = st.columns(3, gap="medium")
        for column, card in zip(columns, cards[start : start + 3]):
            kind, label, actions = card
            with column:
                if kind == "label":
                    show_label_card(label, actions)
                elif kind == "suggested":
                    show_suggested_card(label, actions)
                elif kind == "loose":
                    show_loose_card(actions)
                elif kind == "large":
                    show_large_card(actions)
                else:
                    show_duplicate_card(actions)


def shown_ids(cards: list) -> set[str]:
    found = set()
    for _, _, actions in cards:
        for action in actions:
            found.add(action_id(action))
    return found


def show_loose_card(actions: list[dict]) -> None:
    """Drop target for files that are not in a folder. Removing a label sends its files here."""
    with st.container(border=True, key="card-unfiled"):
        st.markdown(
            f'<p class="cat-head"><span class="cat-name">No folder</span>'
            f'<span class="cat-count">{len(actions)}</span></p>',
            unsafe_allow_html=True,
        )
        show_chips(actions)


def is_ai_placed(action: dict) -> bool:
    """True when the model chose this file's folder."""
    return action.get("reason") == "AI guess" or action.get("source") == "ai"


def ai_guess_count(plan: list[dict], labels: list[dict]) -> int:
    pending = suggested_file_ids()
    shown = [
        label for label in labels if label.get("source") != "suggested"
    ]
    return sum(
        1
        for action in plan
        if is_ai_placed(action) and any(on_label(action, label, pending) for label in shown)
    )


def ai_guess_cards(plan: list[dict], labels: list[dict], pending: set[str]) -> list:
    """Folder cards that hold only the files the AI placed."""
    cards = []
    for label in labels:
        actions = [
            action
            for action in plan
            if is_ai_placed(action) and on_label(action, label, pending)
        ]
        if actions:
            cards.append(("label", label, actions))
    return cards


def on_label(action: dict, label: dict, pending: set[str]) -> bool:
    if action.get("leave") or action.get("destination") == DUPLICATE_FOLDER:
        return False
    if action_id(action) in pending and not action.get("moved_by_you"):
        return False
    # A suggestion stays on the folder the file is in until you accept it.
    if action.get("suggested") and not action.get("moved_by_you"):
        return (action.get("folder") or "") == (label.get("name") or "")
    return action.get("label_key") == label.get("key") or action.get("destination") == label.get("name")


def show_label_card(label: dict, actions: list[dict]) -> None:
    key = label.get("key") or ""
    renaming = bool(st.session_state.get(f"renaming_{key}"))
    with st.container(border=True, key=f"card-{key}"):
        with st.container(key=f"head-{key}", horizontal=True, vertical_alignment="center", gap="small", wrap=False):
            edited = None
            if renaming:
                edited = st.text_input(
                    "Heading",
                    value=label.get("name") or "",
                    key=f"rename_input_{key}",
                    label_visibility="collapsed",
                )
            else:
                st.markdown(
                    f'<p class="cat-head"><span class="cat-name">{html.escape(label.get("name") or "")}</span>'
                    f'<span class="cat-count">{len(actions)}</span></p>',
                    unsafe_allow_html=True,
                )
            if st.button("✎", key=widget_key("pen", key), help="Rename"):
                st.session_state[f"renaming_{key}"] = not renaming
                st.rerun()
        if renaming and edited is not None and edited.strip() != (label.get("name") or ""):
            rename_label(label, edited)
        if st.button("Remove", key=widget_key("remove", key)):
            remove_label(label)
        show_chips(actions)


def show_suggested_card(suggestion: dict, actions: list[dict]) -> None:
    key = suggestion.get("key") or suggestion.get("name") or ""
    with st.container(border=True, key=f"suggest-{widget_key('s', key)}"):
        st.markdown(
            f'<p class="cat-head"><span class="cat-name">{html.escape(suggestion.get("name") or "")}</span>'
            f'<span class="cat-count">{len(actions)}</span></p>',
            unsafe_allow_html=True,
        )
        st.caption("Suggested")
        if st.button("Add", key=widget_key("addsug", key)):
            accept_suggestion(suggestion)
        show_chips(actions)


def show_large_card(actions: list[dict]) -> None:
    """Large files as one card. Not a drop target. The remove choice stays in the preview."""
    with st.container(border=True, key="pile-large"):
        st.markdown(
            f'<p class="cat-head"><span class="cat-name">Large files</span>'
            f'<span class="cat-count">{len(actions)}</span></p>',
            unsafe_allow_html=True,
        )
        show_chips(actions)


def show_duplicate_card(actions: list[dict]) -> None:
    with st.container(border=True, key="pile-duplicates"):
        st.markdown(
            f'<p class="cat-head"><span class="cat-name">Duplicates</span>'
            f'<span class="cat-count">{len(actions)}</span></p>',
            unsafe_allow_html=True,
        )
        show_chips(actions)


def show_chips(actions: list[dict]) -> None:
    if not actions:
        return
    selected = st.session_state.get("selected") or ""
    buttons = []
    for action in actions:
        ident = action_id(action)
        marked = " file-chip-on" if ident == selected else ""
        flag = '<span class="moved-flag">moved</span>' if action.get("moved_by_you") else ""
        buttons.append(
            f'<span class="chip-wrap">{flag}'
            f'<button type="button" class="file-chip{marked}" draggable="true" '
            f'data-file="{html.escape(ident, quote=True)}">{chip_label(action)}</button>'
            f"</span>"
        )
    st.html('<div class="chip-row">' + "".join(buttons) + "</div>")


def install_drag() -> None:
    st.html(
        """
        <script>
        (function () {
          if (window.__careDrag === 3) return;
          window.__careDrag = 3;
          let dragging = false;
          function send(payload) {
            const input = document.querySelector(".st-key-drop_token input");
            if (!input) return;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            setter.call(input, payload);
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));
            // Streamlit sends the value when Enter is pressed.
            setTimeout(() => {
              input.focus();
              input.dispatchEvent(new KeyboardEvent("keydown", {
                key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true
              }));
            }, 30);
          }
          function cardKey(node) {
            const card = node && node.closest ? node.closest('[class*="st-key-card-"], .st-key-pile-duplicates') : null;
            if (!card) return "";
            if (card.classList.contains("st-key-pile-duplicates")) return "duplicates";
            const found = Array.from(card.classList).find((name) => name.indexOf("st-key-card-") === 0);
            return found ? found.slice("st-key-card-".length) : "";
          }
          document.addEventListener("dragstart", (event) => {
            const chip = event.target.closest && event.target.closest(".file-chip");
            if (!chip) return;
            dragging = true;
            event.dataTransfer.setData("text/plain", chip.getAttribute("data-file") || "");
            event.dataTransfer.effectAllowed = "move";
          });
          document.addEventListener("dragend", () => {
            document.querySelectorAll(".drop-over").forEach((node) => node.classList.remove("drop-over"));
            setTimeout(() => { dragging = false; }, 0);
          });
          document.addEventListener("dragover", (event) => {
            const card = event.target.closest && event.target.closest('[class*="st-key-card-"], .st-key-pile-duplicates');
            if (!card) return;
            event.preventDefault();
            card.classList.add("drop-over");
          });
          document.addEventListener("dragleave", (event) => {
            const card = event.target.closest && event.target.closest('[class*="st-key-card-"], .st-key-pile-duplicates');
            if (card) card.classList.remove("drop-over");
          });
          document.addEventListener("drop", (event) => {
            const dest = cardKey(event.target);
            if (!dest) return;
            event.preventDefault();
            const fileId = event.dataTransfer.getData("text/plain");
            if (!fileId) return;
            send(["move", fileId, dest, String(Date.now())].join("\u001f"));
          });
          document.addEventListener("click", (event) => {
            if (dragging) return;
            const tab = event.target.closest && event.target.closest(".nav-tab");
            if (tab) {
              send(["view", tab.getAttribute("data-view") || "files", "", String(Date.now())].join("\u001f"));
              return;
            }
            const chip = event.target.closest && event.target.closest(".file-chip");
            if (!chip) return;
            const fileId = chip.getAttribute("data-file") || "";
            if (!fileId) return;
            send(["select", fileId, "", String(Date.now())].join("\u001f"));
          });
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def take_drop() -> None:
    token = st.session_state.get("drop_token") or ""
    if not token or token == st.session_state.get("drop_seen"):
        return
    # One drop is applied once. A later menu change must not replay it.
    handled = st.session_state.setdefault("handled_drops", [])
    if token in handled:
        st.session_state.drop_seen = token
        st.session_state.drop_token = ""
        return
    handled.append(token)
    if len(handled) > 40:
        del handled[:-40]
    st.session_state.drop_seen = token
    st.session_state.drop_token = ""
    parts = token.split("\x1f")
    kind = parts[0] if parts else ""
    file_id = parts[1] if len(parts) > 1 else ""
    if kind == "view":
        chosen = file_id or "files"
        if chosen in {"files", "duplicates", "Review", "Other", "unfiled", "large", "ai"}:
            st.session_state.file_view = chosen
        st.rerun()
        return
    plan = st.session_state.get("plan") or []
    action = next((item for item in plan if action_id(item) == file_id), None)
    if action is None:
        return
    if kind == "select":
        st.session_state.selected = file_id
    elif kind == "move" and len(parts) > 2:
        assign_label(action, parts[2])
    st.rerun()


def assign_label(action: dict, dest_key: str) -> None:
    if dest_key == "unfiled":
        park_unfiled(action)
        return
    if dest_key == "duplicates":
        send_to_duplicates(action)
        return
    labels = st.session_state.get("labels") or []
    label = next((item for item in labels if item.get("key") == dest_key), None)
    if label is None or label.get("source") == "suggested":
        return
    if (
        not action.get("leave")
        and action.get("label_key") == label.get("key")
        and action.get("destination") == label.get("name")
    ):
        return
    # The Move to menu can still say the old folder. Save sends that value
    # again, and it must not undo this move.
    remember_review()
    remember_previous(action)
    action["move_gen"] = (action.get("move_gen") or 0) + 1
    action["ignore_choice"] = choice_for(action)
    action["leave"] = False
    action["destination"] = label.get("name") or ""
    action["label_key"] = label.get("key") or ""
    action["moved_by_you"] = True
    action["suggested"] = False
    forget_suggestion_file(action)
    mark_unsaved()


def chip_label(action: dict) -> str:
    """File name, with an AI guess shown in blue beside it."""
    name = html.escape(action.get("name") or "file")
    if action.get("reason") == "AI guess":
        return f'{name}<span class="ai-tag">AI guess</span>'
    if action.get("source") == "ai":
        return f'{name}<span class="ai-tag">AI</span>'
    return name


def show_similar_ask() -> None:
    """A close name asks first. The question goes away after Still create or No."""
    pending = (st.session_state.get("pending_label") or "").strip()
    note = st.session_state.get("pending_note") or ""
    if not pending or not note:
        return
    st.markdown(f'<p class="similar-ask">{html.escape(note)}</p>', unsafe_allow_html=True)
    with st.container(horizontal=True, gap="small"):
        if st.button("Still create", key="confirm_similar"):
            create_label_now(pending, "")
        if st.button("No", key="cancel_similar"):
            st.session_state.pending_label = ""
            st.session_state.pending_note = ""
            st.session_state.label_note = ""
            st.rerun()


def show_add_label() -> None:
    if st.session_state.pop("clear_new_name", False):
        st.session_state.new_name = ""
    with st.form("add_label", border=False):
        with st.container(key="add_fields", horizontal=True, vertical_alignment="center", gap="small"):
            name = st.text_input("Name", key="new_name", label_visibility="collapsed", placeholder="")
            submitted = st.form_submit_button("Enter", key="add_label_go")
    if submitted:
        add_user_label(name, "")


def show_field(title: str, value: str) -> None:
    st.markdown(
        f'<p class="field-label">{html.escape(title)}</p><p class="field-value">{html.escape(value)}</p>',
        unsafe_allow_html=True,
    )


def show_details(plan: list[dict]) -> None:
    with st.container(border=True, key="preview_pane"):
        selected = st.session_state.get("selected") or ""
        action = next((item for item in plan if action_id(item) == selected), None)
        with st.container(horizontal=True, vertical_alignment="center", gap="small", key="preview_head"):
            st.markdown('<p class="preview-title">Preview</p>', unsafe_allow_html=True)
            if action is not None and st.button("↻", key="clear_preview", help="Reload"):
                st.session_state.selected = ""
                st.rerun()
        if action is None:
            st.caption("Click a file.")
            return
        record = file_for(action)
        show_field("File name", action.get("name") or "file")
        st.markdown('<p class="field-label">Contents</p>', unsafe_allow_html=True)
        show_preview(record)
        size = record.get("size_bytes")
        show_field("Size", format_bytes(size or 0) if size is not None else "Unknown")
        show_field("Created", show_stamp(record.get("added")))
        show_field("Modified", show_stamp(record.get("modified")))
        show_field("Other notes", notes_for(action, record))
        choose_move(action)
        if large_file(action):
            st.caption("Big file – do you still need it?")
            st.checkbox("Remove when you approve", key=widget_key("aside", action_id(action)))
        path = Path(record.get("path") or "")
        with st.container(horizontal=True, gap="small", key="preview_actions"):
            if st.button("Open file", key="open_file"):
                open_file(path)
            if st.button("Show in folder", key="show_folder"):
                show_in_folder(path)


def notes_for(action: dict, record: dict) -> str:
    """Other notes stay the scan note. Moving a file does not replace them."""
    if record.get("is_duplicate"):
        return duplicate_why(record)
    reason = action.get("reason") or ""
    if reason == "moved by you":
        return "None"
    return reason or "None"


def duplicate_why(record: dict) -> str:
    """Same bytes as the kept file, where each copy sits, and why this one is the extra."""
    files = st.session_state.get("files") or []
    digest = record.get("sha256") or ""
    group = [item for item in files if digest and item.get("sha256") == digest]
    keeper = next((item for item in group if not item.get("is_duplicate")), None)
    if keeper is None:
        kept = record.get("duplicate_of") or "another file"
        return f"Same contents as {kept}. This copy can go to Safe to remove."
    kept_name = keeper.get("name") or "another file"
    here = folder_phrase(record)
    there = folder_phrase(keeper)
    if here == there:
        where = f"Both copies are in {here}."
    else:
        where = f"This copy is in {here}, and {kept_name} is in {there}."
    return f"Same contents as {kept_name}. {where} {why_extra(record, keeper)}"


def folder_phrase(record: dict) -> str:
    return record.get("folder") or "the main folder"


def why_extra(record: dict, keeper: dict) -> str:
    if scanner.is_copy_style(record.get("name") or "") and not scanner.is_copy_style(keeper.get("name") or ""):
        return "This name looks like a copy, so the plain name is kept."
    added = record.get("added") or ""
    kept_added = keeper.get("added") or ""
    if added and kept_added and added > kept_added:
        return "This one was added later, so the older one is kept."
    modified = record.get("modified") or ""
    kept_modified = keeper.get("modified") or ""
    if added == kept_added and modified and kept_modified and modified > kept_modified:
        return "This one was edited later, so the older edit is kept."
    if added == kept_added and modified == kept_modified:
        return "They arrived at the same time, so the other name is kept."
    return "The other copy is the one to keep."


def choice_for(action: dict) -> str:
    """The folder name the Move to menu should show."""
    if action.get("leave"):
        return NO_FOLDER
    if action.get("destination") == DUPLICATE_FOLDER:
        return DUPLICATE_CHOICE
    if action.get("suggested") and not action.get("moved_by_you"):
        return LEAVE
    return action.get("destination") or NO_FOLDER


def move_widget_key(ident: str, action: dict) -> str:
    # A new key after each move, so the menu cannot replay the old folder.
    return f"{widget_key('move', ident)}_{action.get('move_gen') or 0}"


def _on_move_picked(ident: str) -> None:
    """Apply a real change of the Move to menu. Ignore a replay of the old folder."""
    plan = st.session_state.get("plan") or []
    action = next((item for item in plan if action_id(item) == ident), None)
    if action is None:
        return
    # A new drag in this same run is the move. A drop we already applied is not.
    token = st.session_state.get("drop_token") or ""
    handled = st.session_state.get("handled_drops") or []
    if (
        token
        and token not in handled
        and token != st.session_state.get("drop_seen")
        and token.split("\x1f")[0] == "move"
    ):
        return
    # No folder is a holding place. The next folder the user picks is a real move.
    if choice_for(action) == NO_FOLDER:
        action["ignore_choice"] = None
    choice = st.session_state.get(move_widget_key(ident, action))
    if not choice or choice == choice_for(action):
        return
    if replayed_choice(action, choice):
        return
    _apply_choice(action, choice)


def file_is_duplicate(action: dict) -> bool:
    """True when the scan found another file with the same contents."""
    return bool(file_for(action).get("is_duplicate"))


def replayed_choice(action: dict, choice: str) -> bool:
    """A repeated old menu value is ignored. Sending a duplicate back is a real move."""
    if choice != action.get("ignore_choice"):
        return False
    if choice == DUPLICATE_CHOICE and file_is_duplicate(action) and choice_for(action) != DUPLICATE_CHOICE:
        return False
    return True


def send_to_duplicates(action: dict) -> None:
    """Put a duplicate back with the other copies. A normal file is left where it is."""
    if not file_is_duplicate(action):
        return
    if action.get("destination") == DUPLICATE_FOLDER and not action.get("leave"):
        return
    remember_review()
    remember_previous(action)
    action["move_gen"] = (action.get("move_gen") or 0) + 1
    action["ignore_choice"] = choice_for(action)
    action["leave"] = False
    action["destination"] = DUPLICATE_FOLDER
    action["label_key"] = ""
    action["moved_by_you"] = True
    action["suggested"] = False
    forget_suggestion_file(action)
    mark_unsaved()


def remember_previous(action: dict) -> None:
    """The folder this file is leaving. Remove can put it back, and the preview can name it."""
    action["previous"] = {
        "destination": action.get("destination") or "",
        "label_key": action.get("label_key") or "",
        "leave": bool(action.get("leave")),
        "reason": action.get("reason") or "",
        "source": action.get("source") or "",
        "suggested": bool(action.get("suggested")),
        "moved_by_you": bool(action.get("moved_by_you")),
    }
    note_last_location(action)


def note_last_location(action: dict) -> None:
    """Remember the folder this file is leaving, for the preview line."""
    if action.get("leave") or not action.get("destination"):
        action["last_location"] = NO_FOLDER
    elif action.get("destination") == DUPLICATE_FOLDER:
        action["last_location"] = "Duplicates"
    else:
        action["last_location"] = action.get("destination") or NO_FOLDER


def park_unfiled(action: dict) -> None:
    """A drop onto No folder, or the same result as choosing No folder."""
    if action.get("leave"):
        return
    remember_review()
    remember_previous(action)
    action["move_gen"] = (action.get("move_gen") or 0) + 1
    # The next menu choice is a real folder. Do not treat it as the old value.
    action["ignore_choice"] = None
    action["leave"] = True
    action["destination"] = ""
    action["label_key"] = ""
    action["moved_by_you"] = True
    action["suggested"] = False
    forget_suggestion_file(action)
    mark_unsaved()


def _apply_choice(action: dict, choice: str) -> None:
    if choice == choice_for(action):
        return
    if choice in {LEAVE, NO_FOLDER}:
        park_unfiled(action)
        return
    if choice in {DUPLICATE_CHOICE, DUPLICATE_FOLDER}:
        send_to_duplicates(action)
        return
    labels = st.session_state.get("labels") or []
    dest = next((label.get("key") or "" for label in labels if label.get("name") == choice), "")
    assign_label(action, dest)


def choose_move(action: dict) -> None:
    labels = st.session_state.get("labels") or []
    options = [label.get("name") or "" for label in labels if label.get("source") != "suggested" and label.get("name")]
    options.append(NO_FOLDER)
    if file_is_duplicate(action):
        options.append(DUPLICATE_CHOICE)
    if action.get("suggested") and not action.get("moved_by_you"):
        options.append(LEAVE)
    current = choice_for(action)
    if current == NO_FOLDER:
        action["ignore_choice"] = None
    if current not in options:
        options.insert(0, current)
    key = move_widget_key(action_id(action), action)
    incoming = st.session_state.get(key)
    gen = action.get("move_gen") or 0
    if incoming and incoming != current and not replayed_choice(action, incoming):
        # The menu changed. Apply it here too, so a file in No folder can leave.
        previous = current
        _apply_choice(action, incoming)
        if choice_for(action) != previous:
            st.rerun()
        current = choice_for(action)
        key = move_widget_key(action_id(action), action)
    elif incoming == current:
        if action.get("seen_gen") == gen:
            action["ignore_choice"] = None
        action["seen_gen"] = gen
    last = action.get("last_location") or ""
    if last:
        st.markdown(
            f'<p class="last-location">Last location: {html.escape(last)}</p>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="move-gap"></div>', unsafe_allow_html=True)
    if st.session_state.get(key) != current:
        st.session_state[key] = current
    st.selectbox(
        "Move to",
        options,
        key=key,
        on_change=_on_move_picked,
        args=(action_id(action),),
    )


def show_preview(record: dict) -> None:
    path = Path(record.get("path") or "")
    extension = (record.get("extension") or path.suffix).lower()
    if not path.is_file():
        st.write("No preview")
        return
    if extension in IMAGE_TYPES:
        try:
            st.image(str(path))
        except Exception as err:
            log_problem(f"Could not preview {path.name}", err)
            st.write("No preview")
        return
    if extension not in {".txt", ".pdf", ".docx"}:
        st.write("No preview")
        return
    try:
        text = read_preview(path, extension)
    except Exception as err:
        log_problem(f"Could not preview {path.name}", err)
        st.write("No preview")
        return
    if text.strip():
        st.text(text[:PREVIEW_LONG])
        return
    st.write("No preview")


def read_preview(path: Path, extension: str) -> str:
    if extension == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")[:PREVIEW_LONG]
    if extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts = []
        total = 0
        for page in reader.pages:
            piece = page.extract_text() or ""
            parts.append(piece)
            total += len(piece)
            if total >= PREVIEW_LONG:
                break
        return "".join(parts)[:PREVIEW_LONG]
    from docx import Document

    document = Document(str(path))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    return text[:PREVIEW_LONG]


def open_file(path: Path) -> None:
    if not path.is_file():
        notice("error", "That file couldn't be opened.")
        return
    try:
        os.startfile(path)  # noqa: S606 - the user asked to open the file they clicked.
    except OSError as err:
        log_problem(f"Could not open {path}", err)
        notice("error", "That file couldn't be opened.")


def show_in_folder(path: Path) -> None:
    if not path.exists():
        notice("error", "That folder couldn't be opened.")
        return
    try:
        subprocess.Popen(["explorer", f"/select,{path}"])
    except OSError as err:
        log_problem(f"Could not show {path}", err)
        notice("error", "That folder couldn't be opened.")


def show_stamp(value) -> str:
    if not value:
        return "unknown"
    return str(value).replace("T", " ")


def load_review_labels() -> list[dict]:
    try:
        labels = folders.load_labels()
    except (OSError, json.JSONDecodeError, ValueError) as err:
        log_problem("Could not read labels.", err)
        raise ScanStop("The labels couldn't be read.") from err
    # A label you made is kept only after Approve. Saving alone does not.
    return [
        label
        for label in labels
        if label.get("source") != "yours" or label.get("approved")
    ]


def prepare_review(
    files: list, plan: list[dict], labels: list[dict], use_ai: bool, disk_folders: list[str] | None = None
) -> list[dict]:
    include_kept_files(files, plan)
    add_disk_labels(files, labels, disk_folders or [])
    attach_labels(plan, labels)
    suggestions = []
    if use_ai:
        records = file_index(files)
        yours = [label for label in labels if label.get("source") == "yours"]
        if yours:
            place_with_yours(plan, records, yours)
        suggestions = suggested_labels(plan, records, labels)
    hide_empty_labels(plan, labels, disk_folders or [], suggestions)
    return suggestions


def hide_empty_labels(plan: list[dict], labels: list[dict], disk_folders: list[str], suggestions: list[dict]) -> None:
    """Cards come from this folder. A saved label with no files here starts hidden.

    It stays in Move to, so it comes back as soon as a file goes in.
    """
    on_disk = {name.casefold() for name in disk_folders}
    pending = {file_id for item in suggestions for file_id in (item.get("file_ids") or [])}
    for label in labels:
        if label.get("source") not in {"default", "yours"}:
            continue
        if (label.get("name") or "").casefold() in on_disk:
            continue
        if not any(on_label(action, label, pending) for action in plan):
            label["hidden"] = True


def label_shown(label: dict, plan: list[dict], pending: set[str]) -> bool:
    if label.get("source") == "suggested":
        return False
    if not label.get("hidden"):
        return True
    return any(on_label(action, label, pending) for action in plan)


def add_disk_labels(files: list, labels: list[dict], disk_folders: list[str] | None = None) -> None:
    """Every folder in the chosen directory gets a card, even when it is empty."""
    known = {(label.get("name") or "").casefold() for label in labels}
    known.add("_safe_to_remove")
    found = list(disk_folders or [])
    found.extend((record.get("folder") or "").strip() for record in files)
    for name in found:
        name = (name or "").strip()
        if not name or name.casefold() in known:
            continue
        known.add(name.casefold())
        labels.append(
            {
                "key": name,
                "name": name,
                "description": "",
                "source": "disk",
            }
        )


def include_kept_files(files: list, plan: list[dict]) -> None:
    """A file already in the right folder is left out of the plan. Put it back so it stays visible."""
    seen = {action_id(action) for action in plan}
    for record in files:
        current = record.get("folder") or ""
        name = record.get("name") or ""
        if f"{current}/{name}" in seen:
            continue
        plan.append(
            {
                "name": name,
                "folder": current,
                "destination": current,
                "reason": "already in this folder",
                "source": "rule",
            }
        )


def attach_labels(plan: list[dict], labels: list[dict]) -> None:
    by_key = {label["key"]: label for label in labels}
    by_name = {(label.get("name") or "").casefold(): label for label in labels}
    for action in plan:
        destination = action.get("destination") or ""
        if destination == DUPLICATE_FOLDER:
            action["label_key"] = ""
            continue
        label = by_key.get(destination) or by_name.get(destination.casefold())
        if label is None:
            # The suggested folder is gone. A file already in a folder stays there.
            current = (action.get("folder") or "").strip()
            held = by_name.get(current.casefold()) if current else None
            if held is not None:
                action["label_key"] = held["key"]
                action["destination"] = held["name"]
                action["suggested"] = False
                continue
            action["label_key"] = destination
            action["leave"] = True
            continue
        action["label_key"] = label["key"]
        action["destination"] = label["name"]


def place_with_yours(plan: list[dict], records: dict, yours: list[dict]) -> None:
    allowed = {label.get("name") or "" for label in yours}
    for action in plan:
        if not waiting_for_label(action):
            continue
        record = records.get(action_id(action)) or {}
        # Code and web files stay put on a normal scan. Asking the model once per file is slow.
        if (record.get("extension") or "").lower() in classifier.SKIP_AI:
            continue
        try:
            choice = ask_label(record, yours)
        except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError) as err:
            log_problem(f"Could not label {action.get('name')}", err)
            continue
        if choice not in allowed:
            continue
        extension = record.get("extension") or ""
        if not classifier.ai_answer_fits(choice, extension):
            continue
        if (action.get("destination") or "") != choice or action.get("leave"):
            remember_previous(action)
            forget_suggestion_file(action)
        action["destination"] = choice
        action["label_key"] = next(label["key"] for label in yours if label.get("name") == choice)
        action["source"] = "ai"
        action["reason"] = "AI guess"


def suggested_labels(plan: list[dict], records: dict, labels: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for action in plan:
        if not waiting_for_label(action):
            continue
        record = records.get(action_id(action)) or {}
        if (record.get("extension") or "").lower() in classifier.SKIP_AI:
            continue
        try:
            raw = ask_short_name(record)
        except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError) as err:
            log_problem(f"Could not name a folder for {action.get('name')}", err)
            continue
        name = tidy_short_name(raw)
        if not name or folders.validate_name(name, labels):
            continue
        bucket = groups.setdefault(name.casefold(), {"name": name, "file_ids": []})
        bucket["file_ids"].append(action_id(action))
    suggestions = []
    for bucket in groups.values():
        if len(bucket["file_ids"]) < 2:
            continue
        suggestions.append(
            {
                "key": folders.new_key(bucket["name"], labels + suggestions),
                "name": bucket["name"],
                "description": "Suggested from these files.",
                "source": "suggested",
                "file_ids": bucket["file_ids"],
            }
        )
    return suggestions


def waiting_for_label(action: dict) -> bool:
    if action.get("leave") or action.get("moved_by_you") or action.get("suggested"):
        return False
    if action.get("destination") == DUPLICATE_FOLDER:
        return False
    return action.get("label_key") in {"Other", "Review"}


def ask_label(record: dict, yours: list[dict]) -> str:
    lines = "\n".join(f"{label['name']}: {label.get('description') or label['name']}" for label in yours)
    names = [label["name"] for label in yours]
    prompt = (
        f"File name: {record.get('name') or ''}\n"
        f"Text: {(record.get('preview_text') or '')[:300]}\n"
        "\n"
        "Which folder is this file? If none fit, answer Review.\n"
        "\n"
        f"{lines}\n"
        "Review\n"
    )
    data = ask_json(
        prompt,
        {
            "type": "object",
            "properties": {"folder_name": {"type": "string", "enum": names + ["Review"]}},
            "required": ["folder_name"],
        },
    )
    if not data:
        return ""
    return str(data.get("folder_name") or "")


def ask_short_name(record: dict) -> str:
    prompt = (
        f"File name: {record.get('name') or ''}\n"
        f"Text: {(record.get('preview_text') or '')[:300]}\n"
        "\n"
        "Give a folder name of 1 or 2 words for this file.\n"
    )
    data = ask_json(
        prompt,
        {
            "type": "object",
            "properties": {"folder_name": {"type": "string"}},
            "required": ["folder_name"],
        },
    )
    if not data:
        return ""
    return str(data.get("folder_name") or "")


def judge_names(files: list[dict], plan: list[dict], ask: str) -> dict:
    """Rules place the obvious files. Qwen invents folders for the rest."""
    records = {f"{item.get('folder') or ''}/{item.get('name') or ''}": item for item in files}
    pending = [
        records.get(f"{action.get('folder') or ''}/{action.get('name') or ''}") or {}
        for action in plan
        if action.get("destination") != DUPLICATE_FOLDER
    ]
    pending = [record for record in pending if record]
    found = {}
    leftovers = []
    for record in pending:
        ruled = classifier.rule_category(record)
        key = f"{record.get('folder') or ''}/{record.get('name') or ''}"
        if ruled is not None:
            found[key] = ruled[0]
        else:
            leftovers.append(record)
    if not leftovers:
        return found
    # Two models at once on 8 GB makes every call wait. Keep only Qwen.
    free_for_ask()
    folders = invent_folders(leftovers, ask)
    if "Other" not in folders:
        folders.append("Other")
    allowed = {name.casefold(): name for name in folders}
    batch_size = 8
    for start in range(0, len(leftovers), batch_size):
        batch = leftovers[start : start + batch_size]
        chosen = assign_batch(batch, folders, ask)
        for record, name in zip(batch, chosen):
            folder_name = allowed.get(plain_folder(name).casefold(), "")
            key = f"{record.get('folder') or ''}/{record.get('name') or ''}"
            if folder_name:
                found[key] = folder_name
            elif no_clue(record):
                found[key] = "Review"
            else:
                found[key] = "Other"
    return found


def plain_folder(name: str) -> str:
    """Miscellaneous is a junk drawer. The holding folder is Other."""
    cleaned = tidy_short_name(str(name or "").replace("_", " "))
    if cleaned.casefold() in {"miscellaneous", "misc", "general", "various", "uncategorized", "mixed"}:
        return "Other"
    return cleaned


def no_clue(record: dict) -> bool:
    """Review is only for a generic name and almost no text."""
    text = (record.get("preview_text") or "").strip()
    stem = Path(record.get("name") or "").stem.casefold()
    generic = bool(re.fullmatch(r"(doc|document|file|scan|download|untitled|new)[\s_\-]*\d*", stem))
    return len(text) < 20 and generic


def file_line(record: dict) -> str:
    """Same shape as the eval prompt: name, type, then the text in quotes."""
    name = record.get("name") or "file"
    extension = record.get("extension") or Path(name).suffix or "unknown"
    text = ask_snippet(record) or "(none)"
    return (
        f"File name: {name}\n"
        f"File type: {extension}\n"
        "Text (start, middle, and end):\n"
        f'"""\n{text}\n"""'
    )


def ask_snippet(record: dict) -> str:
    """Start, middle, and end. Falls back to the short scan preview."""
    path = record.get("path") or ""
    if path:
        try:
            sample = scanner.text_sample(Path(path))
        except (OSError, ValueError):
            sample = ""
        if sample:
            return sample
    words = " ".join((record.get("preview_text") or "").split())
    return scanner.windows(words) if words else ""


def invent_folders(records: list[dict], ask: str) -> list[str]:
    """One call. Qwen names the folders for this set of files."""
    sample = records
    if len(records) > 24:
        step = len(records) / 24
        sample = [records[int(index * step)] for index in range(24)]
    prompt = (
        f"The user asked: {ask}\n"
        "Invent 4 to 8 folder names that fit these files.\n"
        "Each name is 1 or 2 words. Do not copy a file name.\n"
        "Do not use Miscellaneous or Review. Use Other only as the last resort.\n\n"
        + "\n\n".join(file_line(record) for record in sample)
    )
    data = ask_json(
        prompt,
        {
            "type": "object",
            "properties": {"folders": {"type": "array", "items": {"type": "string"}}},
            "required": ["folders"],
        },
        model=ASK_MODEL,
        timeout=classifier.SLOW_TIMEOUT_SECONDS,
        predict=120,
    )
    raw = data.get("folders") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    names = []
    seen = set()
    file_names = {(record.get("name") or "").casefold() for record in records}
    for item in raw:
        name = plain_folder(str(item))
        key = name.casefold()
        if not name or key in seen or key in file_names or key == "review":
            continue
        seen.add(key)
        names.append(name)
        if len(names) == 8:
            break
    return names


def assign_batch(batch: list[dict], folders: list[str], ask: str) -> list[str]:
    """Put each file into one of the folders Qwen just invented."""
    lines = [f"{number}.\n{file_line(record)}" for number, record in enumerate(batch, start=1)]
    prompt = (
        f"The user asked: {ask}\n"
        "Allowed folders: " + ", ".join(folders) + "\n"
        "For each numbered file, choose the one allowed folder that fits its name and its text.\n"
        "Use Other only when no other folder fits. Never choose Review.\n"
        f"The choices array must have exactly {len(batch)} strings, in file order.\n\n"
        + "\n\n".join(lines)
    )
    data = ask_json(
        prompt,
        {
            "type": "object",
            "properties": {
                "choices": {"type": "array", "items": {"type": "string", "enum": folders}},
            },
            "required": ["choices"],
        },
        model=ASK_MODEL,
        timeout=classifier.SLOW_TIMEOUT_SECONDS,
        predict=max(120, 16 * len(batch)),
    )
    chosen = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(chosen, list):
        return [""] * len(batch)
    names = [str(name) for name in chosen[: len(batch)]]
    names.extend("" for _ in range(len(batch) - len(names)))
    return names


def keep_only(model: str) -> None:
    """Unload every loaded model except this one. An empty name unloads them all."""
    import evaluate

    payload = evaluate.ollama_get("/api/ps")
    if payload is None:
        return
    for loaded in payload.get("models") or []:
        name = str(loaded.get("name") or "") if isinstance(loaded, dict) else ""
        if name and not (model and name.startswith(model)):
            evaluate.unload(name)


def free_for_ask() -> None:
    """Drop any model that is not Qwen, so the 8 GB laptop is not swapping two models."""
    keep_only(ASK_MODEL)


def ask_json(prompt: str, schema: dict, model: str = "", timeout: int = 0, predict: int = 0) -> dict | None:
    options = {"temperature": 0}
    if predict:
        options["num_predict"] = predict
    body = json.dumps(
        {
            "model": model or classifier.MODEL,
            "prompt": prompt,
            "system": "You are a file sorter. You only label files by topic; you never act on them.",
            "stream": False,
            "keep_alive": "30m",
            "format": schema,
            "options": options,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        classifier.OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout or classifier.TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    raw = str(payload.get("response") or "").strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        return None
    return data


def tidy_short_name(raw: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", " ", raw or "")
    words = [word.strip(" .,;:!?'\"()[]") for word in text.split()]
    words = [word for word in words if word][:2]
    if not words:
        return ""
    return " ".join(word[:1].upper() + word[1:] for word in words)


def similar_label_note(name: str, labels: list[dict]) -> str:
    """The question to ask before creating a name close to one that already exists."""
    cleaned = name.strip().casefold()
    close = []
    for label in labels:
        other = (label.get("name") or "").strip()
        if other and names_are_similar(cleaned, other.casefold()) and other not in close:
            close.append(other)
    if not close:
        return ""
    if len(close) == 1:
        return f"{close[0]} is already a label. Still create?"
    listed = ", ".join(close[:-1]) + " and " + close[-1]
    return f"{listed} are already labels. Still create?"


def names_are_similar(left: str, right: str) -> bool:
    if left == right:
        return False
    left_words = name_words(left)
    right_words = name_words(right)
    for word in left_words:
        for other in right_words:
            if word == other:
                return True
            short, long = (word, other) if len(word) <= len(other) else (other, word)
            if len(short) >= 4 and long.startswith(short):
                return True
    return False


def name_words(name: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", name) if len(word) >= 3}


def add_user_label(name: str, description: str) -> None:
    labels = st.session_state.get("labels") or []
    wanted = (name or "").strip().casefold()
    hidden = next(
        (label for label in labels if label.get("hidden") and (label.get("name") or "").casefold() == wanted),
        None,
    )
    if hidden is not None:
        remember_review()
        hidden.pop("hidden", None)
        st.session_state.clear_new_name = True
        st.session_state.show_create = False
        st.rerun()
    error = folders.validate_name(name, labels)
    if error:
        notice("warning", error)
        return
    question = similar_label_note(name, labels)
    if question:
        st.session_state.pending_label = name.strip()
        st.session_state.pending_note = question
        st.session_state.label_note = ""
        st.rerun()
        return
    create_label_now(name, description)


def create_label_now(name: str, description: str) -> None:
    """Create the label, then sort into it when AI is on."""
    labels = st.session_state.get("labels") or []
    error = folders.validate_name(name, labels)
    if error:
        notice("warning", error)
        return
    st.session_state.pending_label = ""
    st.session_state.pending_note = ""
    st.session_state.label_note = ""
    remember_review()
    label = {
        "key": folders.new_key(name, labels),
        "name": name.strip(),
        "description": (description or "").strip(),
        "source": "yours",
    }
    labels.append(label)
    st.session_state.labels = labels
    mark_unsaved()
    if st.session_state.get("scan_mode") == "Rules + AI":
        st.caption("Sorting based on the new label.")
        with st.spinner("Sorting..."):
            place_with_yours(
                st.session_state.get("plan") or [],
                file_index(st.session_state.get("files") or []),
                [item for item in labels if item.get("source") == "yours"],
            )
    clear_move_keys()
    st.session_state.clear_new_name = True
    st.session_state.show_create = False
    st.rerun()


def accept_suggestion(suggestion: dict) -> None:
    labels = st.session_state.get("labels") or []
    error = folders.validate_name(suggestion.get("name") or "", labels)
    if error:
        notice("warning", error)
        return
    remember_review()
    label = {
        "key": folders.new_key(suggestion.get("name") or "", labels),
        "name": suggestion.get("name") or "",
        "description": suggestion.get("description") or "Suggested from these files.",
        "source": "yours",
    }
    labels.append(label)
    st.session_state.labels = labels
    mark_unsaved()
    wanted = set(suggestion.get("file_ids") or [])
    for action in st.session_state.get("plan") or []:
        if action_id(action) not in wanted or action.get("moved_by_you") or action.get("leave"):
            continue
        remember_previous(action)
        action["destination"] = label["name"]
        action["label_key"] = label["key"]
        action["source"] = "ai"
        action["reason"] = "AI guess"
        action["leave"] = False
    st.session_state.suggestions = [
        item for item in (st.session_state.get("suggestions") or []) if item.get("key") != suggestion.get("key")
    ]
    clear_move_keys()
    st.rerun()


def rename_label(label: dict, new_name: str) -> None:
    labels = st.session_state.get("labels") or []
    error = folders.validate_name(new_name, labels, ignore_key=label.get("key") or "")
    if error:
        notice("warning", error)
        return
    remember_review()
    cleaned = new_name.strip()
    old = label.get("name") or ""
    label["name"] = cleaned
    mark_unsaved()
    for action in st.session_state.get("plan") or []:
        if action.get("leave"):
            continue
        if action.get("label_key") == label.get("key") or action.get("destination") == old:
            action["destination"] = cleaned
    st.session_state[f"renaming_{label.get('key')}"] = False
    clear_move_keys()
    st.rerun()


def remove_label(label: dict) -> None:
    remember_review()
    key = label.get("key") or ""
    name = label.get("name") or ""
    labels = [item for item in (st.session_state.get("labels") or []) if item.get("key") != key]
    st.session_state.labels = labels
    for action in st.session_state.get("plan") or []:
        if action.get("destination") == DUPLICATE_FOLDER:
            continue
        if action.get("label_key") == key or action.get("destination") == name:
            put_back(action, labels, name)
    mark_unsaved()
    clear_move_keys()
    st.rerun()


def put_back(action: dict, labels: list[dict], removed_name: str) -> None:
    """Send a file back to the folder it left. No earlier folder means No folder."""
    prev = action.get("previous") or {}
    dest = prev.get("destination") or ""
    prev_key = prev.get("label_key") or ""
    home = None
    if dest and dest != DUPLICATE_FOLDER and not prev.get("leave"):
        for item in labels:
            if prev_key and item.get("key") == prev_key:
                home = item
                break
        if home is None:
            for item in labels:
                if item.get("name") == dest:
                    home = item
                    break
    if home is not None:
        action["leave"] = False
        action["destination"] = home.get("name") or ""
        action["label_key"] = home.get("key") or ""
    elif dest == DUPLICATE_FOLDER and not prev.get("leave"):
        action["leave"] = False
        action["destination"] = DUPLICATE_FOLDER
        action["label_key"] = ""
    else:
        action["leave"] = True
        action["destination"] = ""
        action["label_key"] = ""
    if prev:
        action["reason"] = prev.get("reason") or ""
        action["source"] = prev.get("source") or ""
        action["moved_by_you"] = bool(prev.get("moved_by_you"))
        action.pop("previous", None)
    if home is not None:
        # Stay on the folder card. A suggestion flag would hide that destination.
        action["suggested"] = False
    action["last_location"] = removed_name


def mark_unsaved() -> None:
    """A later edit means the last save no longer matches the screen."""
    st.session_state.labels_dirty = True
    st.session_state.save_note = ""


def remember_review() -> None:
    """Keep the screen as it was, so Undo can step back one change."""
    stack = st.session_state.setdefault("undo_stack", [])
    stack.append(
        {
            "plan": copy.deepcopy(st.session_state.get("plan") or []),
            "labels": copy.deepcopy(st.session_state.get("labels") or []),
            "suggestions": copy.deepcopy(st.session_state.get("suggestions") or []),
            "dirty": bool(st.session_state.get("labels_dirty")),
            "save_note": st.session_state.get("save_note") or "",
        }
    )
    if len(stack) > 20:
        del stack[0]


def reset_to_original() -> None:
    """Put the review back to the way the scan first arranged it."""
    saved = st.session_state.get("original_review")
    if not saved:
        return
    st.session_state.plan = copy.deepcopy(saved["plan"])
    st.session_state.labels = copy.deepcopy(saved["labels"])
    st.session_state.suggestions = copy.deepcopy(saved["suggestions"])
    st.session_state.undo_stack = []
    st.session_state.labels_dirty = False
    st.session_state.save_note = ""
    st.session_state.label_note = ""
    st.session_state.pending_label = ""
    st.session_state.pending_note = ""
    clear_move_keys()


def undo_review_change() -> None:
    stack = st.session_state.get("undo_stack") or []
    if not stack:
        return
    saved = stack.pop()
    st.session_state.plan = saved["plan"]
    st.session_state.labels = saved["labels"]
    st.session_state.suggestions = saved["suggestions"]
    st.session_state.labels_dirty = saved.get("dirty", False)
    st.session_state.save_note = saved.get("save_note") or ""
    clear_move_keys()


def save_review_labels(labels: list[dict]) -> bool:
    try:
        folders.save_labels(labels)
    except OSError as err:
        log_problem("Could not save labels.", err)
        notice("error", "The labels couldn't be saved.")
        return False
    return True


def labels_to_keep(labels: list[dict]) -> list[dict]:
    """Write the current labels, and mark the ones you made as approved."""
    kept = []
    for label in labels:
        if label.get("source") in {"suggested", "disk"}:
            continue
        item = dict(label)
        item.pop("hidden", None)
        if item.get("source") == "yours":
            item["approved"] = True
        kept.append(item)
    return kept


def clear_move_keys() -> None:
    for key in list(st.session_state):
        if str(key).startswith("move_"):
            del st.session_state[key]


def forget_suggestion_file(action: dict) -> None:
    """A file the user moved no longer belongs to a suggestion."""
    ident = action_id(action)
    kept = []
    for item in st.session_state.get("suggestions") or []:
        ids = [file_id for file_id in (item.get("file_ids") or []) if file_id != ident]
        if len(ids) < 2:
            continue
        updated = dict(item)
        updated["file_ids"] = ids
        kept.append(updated)
    st.session_state.suggestions = kept


def suggested_file_ids() -> set[str]:
    found = set()
    for item in st.session_state.get("suggestions") or []:
        found.update(item.get("file_ids") or [])
    return found


def file_index(files: list) -> dict:
    return {f"{item.get('folder') or ''}/{item.get('name') or ''}": item for item in files}


def file_for(action: dict) -> dict:
    return file_index(st.session_state.get("files") or []).get(action_id(action)) or {}


def action_id(action: dict) -> str:
    return f"{action.get('folder') or ''}/{action.get('name') or ''}"


def widget_key(prefix: str, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def show_scan_notes() -> None:
    note = st.session_state.get("ai_note") or ""
    if note:
        notice("warning", note, clear="ai_note")
    skipped = st.session_state.get("skipped") or []
    if not skipped:
        return
    notice("warning", "These files were skipped because they couldn't be opened.", clear="skipped")
    names = "<br>".join(html.escape(name) for name in skipped)
    st.markdown(f'<p class="skipped-list">{names}</p>', unsafe_allow_html=True)


def large_file(action: dict) -> bool:
    """Bigger than LARGE_FILE_MB. The checkbox decides, the sort does not."""
    size = file_for(action).get("size_bytes") or 0
    return size > LARGE_FILE_MB * 1_048_576


def set_aside_ids(plan: list[dict]) -> set[str]:
    found = set()
    for action in plan:
        if not large_file(action):
            continue
        if st.session_state.get(widget_key("aside", action_id(action))):
            found.add(action_id(action))
    return found


def actions_to_apply(plan: list[dict]) -> list[dict]:
    """Labels, your moves, and ticked large files. One list, one Approve."""
    aside = set_aside_ids(plan)
    chosen = [action for action in chosen_actions(plan) if action_id(action) not in aside]
    for action in plan:
        if action_id(action) not in aside:
            continue
        parked = dict(action)
        parked["destination"] = DUPLICATE_FOLDER
        parked["leave"] = False
        parked["suggested"] = False
        chosen.append(parked)
    return chosen


def show_review_lists(plan: list[dict]) -> None:
    """Suggested fixes stay under the cards, and only when there are any."""
    fixes = [
        action
        for action in plan
        if action.get("suggested") and not action.get("moved_by_you") and not action.get("leave")
    ]
    if not fixes:
        return
    st.markdown("**Suggested fixes**")
    for action in fixes:
        reason = action.get("reason") or "A rule says this belongs elsewhere."
        label = f"{action.get('name') or 'file'} — {reason}"
        if st.button(label, key=widget_key("fixrow", action_id(action))):
            st.session_state.selected = action_id(action)
            st.rerun()


def apply_chosen(plan: list[dict]) -> None:
    # A real folder still does not move, and its labels are not kept.
    if not is_test_folder(st.session_state.get("folder") or ""):
        log_problem("Approve did nothing because the scanned folder is not the test folder.")
        notice("warning", "Nothing was moved.")
        return
    chosen = actions_to_apply(plan)
    if not chosen:
        notice("info", "Nothing selected.")
        return
    started = time.perf_counter()
    with st.spinner("Moving..."):
        run_id = executor.apply_plan(
            chosen,
            True,
            executor.log_path_for_folder(),
            suggestions=any(action.get("suggested") for action in chosen),
        )
    if not run_id:
        return
    if not save_review_labels(labels_to_keep(st.session_state.get("labels") or [])):
        return
    st.session_state.labels_dirty = False
    moved = executor.moves_for_run(executor.log_path_for_folder(), run_id)
    moves = [row for row in moved if "from" in row]
    st.session_state.run_id = run_id
    st.session_state.report = {
        "moved": len(moves),
        "set_aside": set_aside_bytes(moves),
        "duplicates": st.session_state.get("duplicates_found") or 0,
        "large": st.session_state.get("large_found") or 0,
        "seconds": st.session_state.get("scan_seconds", 0) + (time.perf_counter() - started),
    }
    st.session_state.screen = "report"
    st.session_state.undo_note = ""
    st.session_state.hold_note = ""
    st.session_state.hold_ask = False
    st.session_state.undo_ask = False
    st.session_state.working = ""
    st.rerun()


def set_aside_bytes(moves: list[dict]) -> int:
    sizes = {}
    for item in st.session_state.get("files") or []:
        sizes[(item.get("folder") or "", item.get("name") or "")] = item.get("size_bytes") or 0
    total = 0
    for row in moves:
        destination = row.get("to") or ""
        if not destination.startswith(f"{DUPLICATE_FOLDER}/"):
            continue
        source = row.get("from") or ""
        if "/" in source:
            folder, name = source.rsplit("/", 1)
        else:
            folder, name = "", source
        total += sizes.get((folder, name), 0)
    return total


def show_report() -> None:
    report = st.session_state.get("report") or {}
    st.subheader("Report")
    one, two, three, four, five = st.columns(5)
    one.metric("Files moved", report.get("moved", 0))
    two.metric("Set aside", format_bytes(report.get("set_aside", 0)))
    three.metric("Duplicates found", report.get("duplicates", 0))
    four.metric("Large files found", report.get("large", 0))
    five.metric("Time", format_seconds(report.get("seconds", 0)))


def show_hold_copies() -> None:
    """Ask first. After a delete, the button there becomes Restore."""
    st.subheader("Delete files")
    st.write("This removes the whole Safe to remove folder.")
    note = st.session_state.get("hold_note") or ""
    if note:
        st.caption(note)
    deleted = False
    try:
        deleted = bool(executor.unrestored_deletions(executor.log_path_for_folder()))
    except Exception as err:
        log_problem("Deleted files could not be checked.", err)
    with st.container(horizontal=True, gap="small"):
        if deleted:
            if st.button("Restore deleted files back?", key="restore_deleted"):
                with st.spinner("Working…"):
                    restore_deleted()
        elif st.button("Delete Safe to remove", key="hold_go"):
            st.session_state.undo_ask = False
            st.session_state.hold_ask = True
            st.rerun()
    # The spinner takes the popup's place on the page, so the popup closes at once.
    if st.session_state.get("working") == "delete":
        st.session_state.working = ""
        with st.spinner("Working…"):
            delete_copies()
    if st.session_state.get("hold_ask") and not deleted:
        delete_dialog()


def delete_copies() -> None:
    """Remove the Safe to remove folder from the test folder. Logged for undo."""
    if not is_test_folder(st.session_state.get("folder") or ""):
        notice("warning", "Nothing was removed.")
        return
    try:
        removed = executor.delete_safe_folder(executor.log_path_for_folder())
    except Exception as err:
        log_problem("Could not delete files.", err)
        notice("error", "Those files couldn't be deleted.")
        return
    if removed is None:
        st.session_state.hold_note = "There is no Safe to remove folder."
    elif removed == 0:
        st.session_state.hold_note = "Removed the Safe to remove folder."
    elif removed == 1:
        st.session_state.hold_note = "Removed the Safe to remove folder, including 1 file."
    else:
        st.session_state.hold_note = f"Removed the Safe to remove folder, including {removed} files."
    st.rerun()


def restore_deleted() -> None:
    """Put the Safe to remove folder back. Stays on this screen."""
    if not is_test_folder(st.session_state.get("folder") or ""):
        notice("warning", "Nothing was restored.")
        return
    try:
        executor.restore_deleted_files(executor.log_path_for_folder())
    except Exception as err:
        log_problem("Could not restore files.", err)
        notice("error", "Those files couldn't be put back.")
        return
    st.session_state.hold_note = "Deleted files are back."
    st.rerun()


def show_disk() -> None:
    status = health.disk_status()
    st.subheader("Disk")
    st.write(f"Used {format_bytes(status['used'])}")
    st.caption("Space already filled on this drive.")
    st.write(f"Free {format_bytes(status['free'])}")
    st.caption("Space you can still use.")


def show_battery() -> None:
    st.subheader("Battery")
    if not st.session_state.get("battery_ready"):
        with st.spinner("Loading"):
            st.session_state.battery_percent = health.battery_health()
            st.session_state.battery_ready = True
    percent = st.session_state.get("battery_percent")
    if percent is None:
        st.write("No battery")
        st.caption("This PC did not report a battery.")
        return
    st.write(f"{percent}% of design capacity")
    st.caption("How full the battery can get, compared with when it was new.")


def format_bytes(size: int) -> str:
    if size >= 1_048_576:
        return f"{size / 1_048_576:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} bytes"


def format_seconds(seconds: float) -> str:
    if seconds >= 60:
        minutes = int(seconds // 60)
        rest = int(seconds % 60)
        return f"{minutes} min {rest} s"
    return f"{seconds:.1f} s"


if __name__ == "__main__":
    main()
