"""Plan where each file would go. This module never moves or renames anything."""

import argparse

import classifier
from config import CATEGORIES, TEST_FOLDER
from scanner import scan_folder

DUPLICATE_FOLDER = "_safe_to_remove"


def build_plan(files, use_ai=True, debug=False) -> list[dict]:
    """One move action per file. Duplicates go to _safe_to_remove."""
    plan = []
    for file in files:
        name = file.get("name") or ""
        if file.get("is_duplicate"):
            plan.append(
                {
                    "name": name,
                    "destination": DUPLICATE_FOLDER,
                    "reason": "duplicate of an older file",
                    "source": "rule",
                }
            )
            continue
        category, reason, source = classifier.classify(file, use_ai=use_ai)
        if debug and source == "ai":
            # Show the exact text sent to Ollama and the text it sent back.
            print(f"--- {name} ---")
            print(classifier.last_prompt)
            print("--- raw answer ---")
            print(classifier.last_raw)
            print()
        plan.append(
            {
                "name": name,
                "destination": category,
                "reason": reason,
                "source": source,
            }
        )
    return plan


def summary(plan) -> str:
    """One plain-English sentence, such as 'Move 42 files into Receipts...'."""
    counts: dict[str, int] = {}
    for action in plan:
        destination = action["destination"]
        counts[destination] = counts.get(destination, 0) + 1
    if not counts:
        return "Nothing to move."
    order = [name for name in list(CATEGORIES) + ["Review", DUPLICATE_FOLDER] if counts.get(name)]
    for name in counts:
        if name not in order:
            order.append(name)
    pieces = [phrase(name, counts[name]) for name in order]
    if len(pieces) == 1:
        body = pieces[0]
    else:
        body = ", ".join(pieces[:-1]) + ", and " + pieces[-1]
    return f"Move {body}."


def phrase(destination: str, count: int) -> str:
    noun = "file" if count == 1 else "files"
    if destination == DUPLICATE_FOLDER:
        return f"{count} duplicate {noun} into {DUPLICATE_FOLDER}"
    return f"{count} {noun} into {destination}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print a move plan for the test folder. Does not move anything."
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Use rules only. Do not ask Ollama.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="For each AI file, print the prompt sent and the raw answer.",
    )
    args = parser.parse_args()
    plan = build_plan(scan_folder(TEST_FOLDER), use_ai=not args.no_ai, debug=args.debug)
    print(summary(plan))
    print()
    for action in plan:
        print(
            f"{action['name']} -> {action['destination']} "
            f"({action['source']}: {action['reason']})"
        )


if __name__ == "__main__":
    main()
