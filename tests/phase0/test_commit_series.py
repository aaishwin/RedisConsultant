"""AC-4 (FR-5): the tier-L scripted 20-commit series with all seven change kinds."""

import json
from collections import Counter
from pathlib import Path

COMMIT_SERIES_PATH = Path("evaltools/corpus/commit-series.json")
EXPECTED_COMMIT_COUNT = 20
SEVEN_CHANGE_KINDS = (
    "modified_body",
    "renamed_file",
    "deleted_file",
    "changed_signature",
    "modified_key_template",
    "grammar_relevant_syntax",
    "no_op",
)


def test_commit_series_is_exactly_twenty_ordered_commits() -> None:
    series = json.loads(COMMIT_SERIES_PATH.read_text(encoding="utf-8"))
    assert series["schema_version"] == "eval-schema 0.1.1"
    assert series["tier"] == "L"
    commits = series["commits"]
    assert len(commits) == EXPECTED_COMMIT_COUNT
    assert [commit["commit_index"] for commit in commits] == list(
        range(1, EXPECTED_COMMIT_COUNT + 1)
    )
    for commit in commits:
        assert commit["change_kind"] in SEVEN_CHANGE_KINDS
        assert len(commit["files"]) >= 1
        for file_change in commit["files"]:
            assert file_change["path"]
            if commit["change_kind"] == "renamed_file":
                assert file_change["prior_path"] is not None, (
                    "a renamed_file commit must cite prior_path"
                )


def test_commit_series_contains_all_seven_change_kinds() -> None:
    series = json.loads(COMMIT_SERIES_PATH.read_text(encoding="utf-8"))
    present_kinds = {commit["change_kind"] for commit in series["commits"]}
    for change_kind in SEVEN_CHANGE_KINDS:
        assert change_kind in present_kinds, (
            f"change kind {change_kind!r} missing from the 20-commit series"
        )
    kind_counts = Counter(commit["change_kind"] for commit in series["commits"])
    assert sum(kind_counts.values()) == EXPECTED_COMMIT_COUNT
