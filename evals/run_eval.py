"""Run the eval from the command line. Read-only for the tested folder.

    python evals/run_eval.py
    python evals/run_eval.py --setups rules llama3.2:1b --both-prompts
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import TEST_FOLDER
from evaluate import RULES_ONLY, SETUPS, duplicate_line, run_eval, slice_table, summary_table


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grade the sorter against labels.csv. Moves nothing.")
    parser.add_argument("--folder", default=TEST_FOLDER, help=f"Folder to grade (default: {TEST_FOLDER}).")
    parser.add_argument("--labels", default=None, help="Answer key (default: labels.csv next to the folder).")
    parser.add_argument(
        "--setups",
        nargs="+",
        default=None,
        help=f"Any of: rules {' '.join(SETUPS[1:])} (default: all).",
    )
    parser.add_argument("--no-reason", action="store_true", help="Ask for a category only.")
    parser.add_argument("--both-prompts", action="store_true", help="Run with and without a reason.")
    parser.add_argument("--seed", type=int, default=None, help="Seed the folder was made with, for the report.")
    return parser.parse_args()


def pick_setups(names) -> list[str]:
    if not names:
        return list(SETUPS)
    chosen = []
    for name in names:
        setup = RULES_ONLY if name.lower() in {"rules", "rules only"} else name
        if setup not in SETUPS:
            sys.exit(f"Unknown setup {name!r}. Choose from: rules {' '.join(SETUPS[1:])}")
        chosen.append(setup)
    return chosen


def show_progress(setup: str, done: int, total: int) -> None:
    if total <= 0:
        print(f"\r{setup}: no files to grade", end="", flush=True)
        return
    if done == 0:
        print(f"\r{setup}: loading…", end="", flush=True)
        return
    end = "\n" if done == total else ""
    print(f"\r{setup}: {done}/{total}", end=end, flush=True)


def main() -> None:
    args = parse_args()
    folder = Path(args.folder)
    labels = Path(args.labels) if args.labels else folder.parent / "labels.csv"
    if args.both_prompts:
        with_reason = (True, False)
    else:
        with_reason = not args.no_reason
    try:
        results = run_eval(
            folder, labels, pick_setups(args.setups), with_reason, progress=show_progress, seed=args.seed
        )
    except (OSError, ValueError) as err:
        sys.exit(str(err))
    print()
    for note in results["skipped"] + results["warnings"]:
        print(f"Note: {note}")
    if results["runs"]:
        print(summary_table(results))
        print()
        print(
            slice_table(
                "AI accuracy by category (AI-decided files only)",
                results["runs"],
                "by_category",
                ["Receipts", "School", "Work", "Other", "Screenshots", "Installers", "Archives", "Photos"],
            )
        )
        print()
        print(
            slice_table(
                "AI accuracy by difficulty (AI-decided files only)",
                results["runs"],
                "by_difficulty",
                ["clear", "edge", "normal"],
            )
        )
    else:
        print("Nothing ran.")
    print(duplicate_line(results))
    if results["folder_unchanged"]:
        print("Folder unchanged.")
    else:
        print("WARNING: the folder changed during the eval:")
        for line in results["folder_changes"]:
            print(f"  {line}")
    if results["csv_path"]:
        print(f"Saved {results['csv_path']}")
        print(f"Saved {results['md_path']}")


if __name__ == "__main__":
    main()
