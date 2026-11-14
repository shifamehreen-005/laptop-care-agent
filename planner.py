"""Plan where each file would go. This module never moves or renames anything."""

import argparse

import classifier
from config import CATEGORIES, TEST_FOLDER
from scanner import scan_folder

DUPLICATE_FOLDER = "_safe_to_remove"


def build_plan(files, use_ai=True, debug=False) -> list[dict]:
    """One move action per file that should move. Duplicates go to _safe_to_remove."""
    plan = []
    for file in files:
        name = file.get("name") or ""
        current = file.get("folder") or ""
        if file.get("is_duplicate"):
            kept = file.get("duplicate_of") or ""
            plan.append(
                {
                    "name": name,
                    "folder": current,
                    "destination": DUPLICATE_FOLDER,
                    "reason": f"copy of {kept}",
                    "source": "rule",
                }
            )
            continue
        # A file the user already filed stays, unless a rule is sure it belongs elsewhere.
        if current:
            suggestion = suggested_fix(file, current)
            if suggestion is not None:
                plan.append(suggestion)
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
                "folder": "",
                "destination": category,
                "reason": reason,
                "source": source,
            }
        )
    return plan


def suggested_fix(file, current: str) -> dict | None:
    """A rule-only suggestion. The AI is not asked about a file that already has a folder."""
    ruled = classifier.rule_category(file)
    if ruled is None:
        return None
    category = ruled[0]
    if category == current:
        return None
    name = file.get("name") or ""
    return {
        "name": name,
        "folder": current,
        "destination": category,
        "reason": f"{name} is in {current} but looks like {category}",
        "source": "rule",
        "suggested": True,
    }


def summary(plan) -> str:
    """The move sentence, then one line for each suggested fix."""
    suggestions = [action for action in plan if action.get("suggested")]
    moves = [action for action in plan if not action.get("suggested")]
    if moves:
        lines = [move_summary(moves)]
    elif not suggestions:
        return "Nothing to move."
    else:
        lines = []
    lines.extend(action["reason"] for action in suggestions)
    return "\n".join(lines)


def move_summary(plan) -> str:
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
