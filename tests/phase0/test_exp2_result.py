"""AC-7 (FR-8, NFR-2): EXP-2 artifact consistency — including its honest `fail`.

The known, user-decided outcome is that the EXP-2 gate is **undemonstrated**:
precision is 0.0 (undefined, TP+FP=0) and recall is 0.0 (0/38). This module
therefore does not assert a pass; it asserts that the committed artifact
internally consistent, code-computed, and records the failed gate honestly
(``verdict == "fail"``), so AC-7 is reported ``unmet`` in qa/run-1.json with
this artifact as evidence.
"""

import json
from pathlib import Path

EXP2_RESULT_PATH = Path("results/exp2.json")
LABELS_PATH = Path("evaltools/exp2/labels.json")
EXPECTED_TOLERANCE = (
    "exact per-callsite match on resolved_depth and tier; template_correct must match"
)
PRECISION_THRESHOLD = 0.80


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_exp2_artifact_declares_the_frozen_labels_and_pin() -> None:
    result = _load_json(EXP2_RESULT_PATH)
    labels = _load_json(LABELS_PATH)
    assert result["schema_version"] == "eval-schema 0.1.1"
    assert result["repo"] == "bullmq"
    assert result["commit_sha"] == labels["pinned_sha"]
    assert result["pinned_sha"] == "f42514c3d716dc81c2bbc65b883c9dc545fcb56d"
    assert result["method"] == "tree_sitter_parse"
    assert result["tolerance"] == EXPECTED_TOLERANCE


def test_exp2_per_label_rows_match_the_frozen_label_set_one_to_one() -> None:
    result = _load_json(EXP2_RESULT_PATH)
    label_ids = [entry["callsite_id"] for entry in _load_json(LABELS_PATH)["entries"]]
    per_label_ids = [row["callsite_id"] for row in result["per_label"]]
    assert per_label_ids == label_ids, "per_label rows are not 1:1 with the labels"


def test_exp2_confusion_matrix_is_recomputable_from_the_rows() -> None:
    result = _load_json(EXP2_RESULT_PATH)
    classifications = [row["classification"] for row in result["per_label"]]
    recomputed = {
        "true_positives": classifications.count("true_positive"),
        "false_positives": classifications.count("false_positive"),
        "false_negatives": classifications.count("false_negative"),
        "true_negatives": classifications.count("true_negative"),
    }
    assert recomputed["true_positives"] == result["true_positives"]
    assert recomputed["false_positives"] == result["false_positives"]
    assert recomputed["false_negatives"] == result["false_negatives"]
    assert recomputed["true_negatives"] == result["true_negatives"]
    assert result["label_count"] == sum(recomputed.values())
    assert result["positive_label_count"] == (
        recomputed["true_positives"] + recomputed["false_negatives"]
    )
    assert result["negative_label_count"] == (
        recomputed["false_positives"] + recomputed["true_negatives"]
    )


def test_exp2_records_the_undemonstrated_gate_honestly() -> None:
    """The 0/0 precision is recorded as 0.0 with a note, and the verdict fails."""
    result = _load_json(EXP2_RESULT_PATH)
    denominator = result["true_positives"] + result["false_positives"]
    if denominator == 0:
        assert result["precision"] == 0.0
        assert result["precision_note"], (
            "a degenerate 0/0 precision must carry an explanatory precision_note, "
            "never a vacuous number alone"
        )
        assert result["recall"] == 0.0
        assert result["false_negatives"] > 0
    assert result["precision"] < PRECISION_THRESHOLD
    # The verdict is the code-computed gate outcome: 0.0 < 0.80 ⇒ fail (D3).
    assert result["verdict"] == "fail"
    assert result["measurement_environment"]["label"] == "advisory"
    assert result["measurement_environment"]["is_reference_profile"] is False


def test_exp2_pipeline_block_is_consistent_with_its_rows() -> None:
    result = _load_json(EXP2_RESULT_PATH)
    pipeline_block = result["measurements"]["pipeline"]
    classifications = [row["classification"] for row in pipeline_block["per_label"]]
    assert classifications.count("true_positive") == pipeline_block["true_positives"]
    assert classifications.count("false_negative") == pipeline_block["false_negatives"]
    assert classifications.count("true_negative") == pipeline_block["true_negatives"]
    assert pipeline_block["precision"] < PRECISION_THRESHOLD
    assert pipeline_block["verdict"] == "fail"
