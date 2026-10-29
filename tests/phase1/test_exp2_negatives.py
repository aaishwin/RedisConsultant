"""AC-20: the 14 negative EXP-2 labels stay true negatives (no false positives)."""

from pathlib import Path

from conftest import checkout_root  # noqa: F401  (fixture: skips when checkout absent)
from qa_support import LABELS_PATH

from evaltools.exp2.harness import (
    checkout_source_path,
    classify_labels,
    collect_predictions_for_labelled_files,
    load_label_records,
)
from redis_intel.frontend import LanguageFrontend


def test_label_set_is_the_frozen_52_entry_set() -> None:
    _labels_payload, records = load_label_records(LABELS_PATH)
    assert len(records) == 52
    positives = [record for record in records if record.expected_is_redis_callsite]
    negatives = [record for record in records if not record.expected_is_redis_callsite]
    assert len(positives) == 38
    assert len(negatives) == 14


def test_all_fourteen_negative_labels_stay_true_negatives(
    checkout_root: Path,  # noqa: F811  (session fixture; skips without the checkout)
) -> None:
    """Run the C-1 frontend over the labelled files and assert zero false positives.

    This is the same measurement shape as the EXP-2 harness (same-file span
    overlap + method equality), executed read-only against the pinned checkout.
    """
    _labels_payload, records = load_label_records(LABELS_PATH)
    frontend = LanguageFrontend()
    labelled_files = sorted({record.file for record in records})
    predictions_by_file = collect_predictions_for_labelled_files(
        frontend, labelled_files
    )
    per_label_rows, confusion_counts, _unmatched_prediction_count = classify_labels(
        records, predictions_by_file
    )
    assert confusion_counts["false_positives"] == 0, (
        "at least one negative label was predicted as a Redis callsite — the "
        "R5 negatives regressed"
    )
    assert confusion_counts["true_negatives"] == 14
    negative_ids = {
        record.callsite_id
        for record in records
        if not record.expected_is_redis_callsite
    }
    for row in per_label_rows:
        if row["callsite_id"] in negative_ids:
            assert row["classification"] == "true_negative", row
            assert row["predicted"] is False


def test_each_negative_label_span_carries_no_callsite_in_its_file(
    checkout_root: Path,  # noqa: F811
) -> None:
    _labels_payload, records = load_label_records(LABELS_PATH)
    frontend = LanguageFrontend()
    negatives = [record for record in records if not record.expected_is_redis_callsite]
    assert len(negatives) == 14
    for record in negatives:
        source_path = checkout_source_path(record.file)
        parse_result = frontend.parse(record.file, source_path.read_bytes())
        overlapping_same_method = [
            callsite
            for callsite in parse_result.redis_callsites
            if callsite.method == record.method
            and callsite.span.start_line <= record.end_line
            and record.start_line <= callsite.span.end_line
        ]
        assert not overlapping_same_method, (
            f"{record.callsite_id}: {record.file}:{record.start_line} "
            f"{record.method} predicted as a Redis callsite"
        )


def test_negative_label_lines_exist_in_the_pinned_checkout(
    checkout_root: Path,  # noqa: F811
) -> None:
    _labels_payload, records = load_label_records(LABELS_PATH)
    negatives = [record for record in records if not record.expected_is_redis_callsite]
    for record in negatives:
        source_path = checkout_source_path(record.file)
        source_lines = source_path.read_text(encoding="utf-8").splitlines()
        assert record.start_line <= len(source_lines), (
            f"{record.callsite_id}: labelled line {record.start_line} beyond the file"
        )
