"""Hard-file keyword guard and --hard 30 plan/labels."""

import csv
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import make_test_folder as m


def test_keyword_check_catches_planted_keyword():
    with pytest.raises(SystemExit, match="invoice"):
        m.assert_no_rule_keywords("doc.txt", "This note mentions an invoice for the desk.")


def test_hard_30_creates_thirty_labeled_files(tmp_path):
    rng = random.Random(42)
    used = {name for name, _category, _text in m.HARD_FILES}
    plans = m.extra_hard_plans(rng, used)
    assert len(plans) == 30
    assert sum(1 for item in plans if item.category == "Receipts") == 8
    assert sum(1 for item in plans if item.category == "School") == 8
    assert sum(1 for item in plans if item.category == "Work") == 8
    assert sum(1 for item in plans if item.category == "Other") == 6
    assert sum(1 for item in plans if item.difficulty == "clear") == 20
    assert sum(1 for item in plans if item.difficulty == "edge") == 10
    assert all(item.source is None for item in plans)
    assert all(item.body for item in plans)

    folder = tmp_path / "Downloads"
    folder.mkdir()
    m.write_plans(folder, plans, seed=42)
    labels_path = tmp_path / "labels.csv"
    m.write_labels(labels_path, plans)

    assert len(list(folder.iterdir())) == 30
    with labels_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0].keys() >= {"filename", "true_category", "is_duplicate", "difficulty"}
    assert len(rows) == 30
    assert all(row["is_duplicate"] == "no" for row in rows)
    assert {row["difficulty"] for row in rows} == {"clear", "edge"}

    # Same seed rebuilds the same names and wording.
    again = m.extra_hard_plans(random.Random(42), {name for name, _c, _t in m.HARD_FILES})
    assert [item.name for item in again] == [item.name for item in plans]
    assert [item.body for item in again] == [item.body for item in plans]
