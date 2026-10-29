"""EXP-2 harness payload helpers (style contract rule 8).

Split out of evaltools/exp2/harness.py; that module re-exports these names.
"""


from evaltools.envreport import build_measurement_environment
from evaltools.exp2.harness_classify import compute_precision, compute_recall
from evaltools.exp2.harness_constants import (
    PRECISION_THRESHOLD,
    RESULT_ARTIFACT,
    RESULT_SCHEMA_VERSION,
    TOLERANCE_TEXT,
    VERDICT_VALUES,
)
from evaltools.exp2.harness_labels import LabelRecord
from evaltools.gate_evidence import (
    require_known_enum,
)


def build_measurement_interpretation(
    surface: str,
    true_positives: int,
    false_positives: int,
    positive_label_count: int,
    precision: float,
    recall: float,
) -> str:
    """State in words what the measured precision/recall pair does and does not show."""
    predicted_positive_count = true_positives + false_positives
    if predicted_positive_count == 0:
        return (
            f"precision is undefined and recorded as 0.0: the {surface} produced 0 "
            f"predictions over the labelled sample against {positive_label_count} "
            f"positive labels, so recall is {recall:.3f} ({true_positives}/"
            f"{positive_label_count}) — there is nothing for a precision figure to "
            "describe; the numbers do not demonstrate NFR-2's intent (>= 0.80 "
            "precision on resolvable wrapper-resolved sites) in either direction, "
            "and the 'fail' verdict records 'gate undemonstrated', not 'every "
            "prediction wrong'"
        )
    headline = (
        f"precision {precision:.3f} rests on {predicted_positive_count} predictions "
        f"(TP {true_positives}, FP {false_positives}) against "
        f"{positive_label_count} positive labels; recall {recall:.3f} "
        f"(TP/{positive_label_count})."
    )
    if recall >= PRECISION_THRESHOLD:
        return (
            headline + " The prediction set covers most of the positive labels, so the "
            "precision figure is supported by enough matched predictions to be "
            "meaningful for this labelled sample."
        )
    return (
        headline
        + f" The precision figure is NOT supported by enough predictions to mean "
        f"anything: the {surface} matches only {true_positives} of the "
        f"{positive_label_count} positive labels, so precision is computed over a "
        "small, structurally biased subsample of real callsites and a high value "
        "over a near-empty match set would be vacuous — these numbers do not "
        "demonstrate NFR-2's intent."
    )


def build_result_payload(
    labels_payload: dict[str, object],
    records: list[LabelRecord],
    per_label_rows: list[dict[str, object]],
    confusion_counts: dict[str, int],
    unmatched_prediction_count: int,
) -> dict[str, object]:
    """Assemble the §3.7 result file with a code-computed §4 verdict."""
    true_positives = confusion_counts["true_positives"]
    false_positives = confusion_counts["false_positives"]
    false_negatives = confusion_counts["false_negatives"]
    true_negatives = confusion_counts["true_negatives"]
    label_count = len(records)
    if (
        label_count
        != true_positives + false_positives + false_negatives + true_negatives
    ):
        raise ValueError(
            f"count invariant broken: {label_count} labels != "
            f"{true_positives}+{false_positives}+{false_negatives}+{true_negatives} "
            "(TP+FP+FN+TN)"
        )
    predicted_positive_count = true_positives + false_positives
    if predicted_positive_count == 0:
        precision = 0.0
        precision_note: str | None = (
            "degenerate precision: the extractor produced 0 callsite predictions "
            "over the labelled sample, so TP + FP == 0 and TP / (TP + FP) is "
            "undefined (0/0); recorded as 0.0 with this note, never as a vacuous "
            "pass — the extractor recognised none of the positive labels"
        )
    else:
        precision = compute_precision(true_positives, false_positives)
        precision_note = None
    positive_count = sum(1 for record in records if record.expected_is_redis_callsite)
    if positive_count == 0:
        recall = 0.0
        recall_note: str | None = (
            "degenerate recall: the label set contains 0 positive labels, so "
            "TP + FN == 0 and TP / (TP + FN) is undefined (0/0); recorded as 0.0"
        )
    else:
        recall = compute_recall(true_positives, false_negatives)
        recall_note = None
    measurement_interpretation = build_measurement_interpretation(
        "C-1 extractor",
        true_positives,
        false_positives,
        positive_count,
        precision,
        recall,
    )
    verdict = "pass" if precision >= PRECISION_THRESHOLD else "fail"
    require_known_enum(verdict, VERDICT_VALUES, RESULT_ARTIFACT, "verdict")
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "artifact": RESULT_ARTIFACT,
        "repo": "bullmq",
        "commit_sha": labels_payload["pinned_sha"],
        "pinned_sha": labels_payload["pinned_sha"],
        "pinned_tag": labels_payload["pinned_tag"],
        "method": "tree_sitter_parse",
        "tolerance": TOLERANCE_TEXT,
        "label_count": label_count,
        "positive_label_count": positive_count,
        "negative_label_count": label_count - positive_count,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "true_negatives": true_negatives,
        "unmatched_prediction_count": unmatched_prediction_count,
        "matching_note": (
            "predictions overlapping no label are counted in "
            "unmatched_prediction_count, not as false positives: the label set is a "
            "deliberate sample (sampling_rule in labels.json), so a detection outside "
            "the sample is not an extraction error"
        ),
        "precision": precision,
        "precision_note": precision_note,
        "recall": recall,
        "recall_note": recall_note,
        "measurement_interpretation": measurement_interpretation,
        "precision_threshold": PRECISION_THRESHOLD,
        "measurement_environment": build_measurement_environment(),
        "verdict": verdict,
        "fetch_command": None,
        "per_label": per_label_rows,
    }
