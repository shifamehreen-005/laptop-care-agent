"""Ask an agent builds folders from the ask, without moving files."""

import ask_agent


def test_group_by_type_gives_every_extension_a_folder() -> None:
    plan = [
        {"name": "a.html", "folder": "", "destination": "Review", "label_key": "Review"},
        {"name": "b.css", "folder": "", "destination": "Review", "label_key": "Review"},
        {"name": "c.pdf", "folder": "", "destination": "Receipts", "label_key": "Receipts"},
        {"name": "copy.html", "folder": "", "destination": "_safe_to_remove"},
    ]
    files = [
        {"name": "a.html", "folder": "", "extension": ".html"},
        {"name": "b.css", "folder": "", "extension": ".css"},
        {"name": "c.pdf", "folder": "", "extension": ".pdf"},
        {"name": "copy.html", "folder": "", "extension": ".html"},
    ]
    labels, new, note = ask_agent.apply_ask(plan, files, "Group by file type")
    assert "extension" in note.casefold() or "type" in note.casefold()
    assert {label["name"] for label in labels} == {"HTML", "CSS", "PDFs"}
    assert [(row["name"], row["destination"]) for row in new] == [
        ("a.html", "HTML"),
        ("b.css", "CSS"),
        ("c.pdf", "PDFs"),
        ("copy.html", "_safe_to_remove"),
    ]


def test_pick_mode() -> None:
    assert ask_agent.pick_mode("Group by file type") == "type"
    assert ask_agent.pick_mode("Sort by what's inside") == "judge"
    assert ask_agent.pick_mode("semester wise folders") == "judge"
    assert ask_agent.pick_mode("organize this") == "judge"


def test_judge_uses_the_names_it_is_given() -> None:
    plan = [
        {"name": "a.html", "folder": "", "destination": "Review", "label_key": "Review"},
        {"name": "b.html", "folder": "", "destination": "Review", "label_key": "Review"},
    ]
    files = [
        {"name": "a.html", "folder": "", "extension": ".html", "preview_text": "css lab"},
        {"name": "b.html", "folder": "", "extension": ".html", "preview_text": "css lab"},
    ]
    labels, new, note = ask_agent.apply_ask(
        plan,
        files,
        "Sort by what's inside",
        name_for_file=lambda record: "Web Lab",
    )
    assert "qwen" in note
    assert {label["name"] for label in labels} == {"Web Lab"}
    assert new[0]["destination"] == "Web Lab"
    assert new[1]["destination"] == "Web Lab"


def test_a_missing_answer_keeps_the_scan_folder() -> None:
    plan = [
        {"name": "a.pdf", "folder": "", "destination": "Receipts", "label_key": "Receipts"},
    ]
    files = [{"name": "a.pdf", "folder": "", "extension": ".pdf"}]
    labels, new, _note = ask_agent.apply_ask(
        plan,
        files,
        "Sort by what's inside",
        name_for_file=lambda record: "",
    )
    assert new[0]["destination"] == "Receipts"
    assert {label["name"] for label in labels} == {"Receipts"}


if __name__ == "__main__":
    test_group_by_type_gives_every_extension_a_folder()
    test_pick_mode()
    test_judge_uses_the_names_it_is_given()
    test_a_missing_answer_keeps_the_scan_folder()
    print("ok")
