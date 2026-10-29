"""EXP-2 harness pipeline helpers (style contract rule 8).

Split out of evaltools/exp2/harness.py; that module re-exports these names.
"""

from evaltools.exp2.harness_classify import compute_precision, compute_recall
from evaltools.exp2.harness_constants import (
    CLASSIFICATION_FALSE_NEGATIVE,
    CLASSIFICATION_FALSE_POSITIVE,
    CLASSIFICATION_TRUE_NEGATIVE,
    CLASSIFICATION_TRUE_POSITIVE,
    MODE_PIPELINE,
    PIPELINE_ATTRIBUTION_NOTE,
    PRECISION_THRESHOLD,
    RESULT_ARTIFACT,
    TOLERANCE_TEXT,
    VERDICT_VALUES,
)
from evaltools.exp2.harness_labels import LabelRecord
from evaltools.exp2.harness_payload import build_measurement_interpretation
from evaltools.gate_evidence import (
    require_known_enum,
)
from redis_intel.ir import IrDelta


def pipeline_predictions_by_label(
    delta: IrDelta, records: list[LabelRecord]
) -> dict[str, list[tuple[str, int]]]:
    """Collect the pipeline's per-label attribution evidence from one IrDelta.

    ``FileRow`` rows are 1-based positional (``file_id = index + 1``, set by
    ``_ingest_one``), so ``Op.file_id`` is resolved through that ordering.
    A label is predicted when an ``Op`` row names the label's file, equals
    its method, and its ``Op.line`` lies inside the label span (1-based
    inclusive, the same convention as ``redis_intel.frontend.Span``).
    """
    file_paths_by_id = {
        file_id: file_row.path for file_id, file_row in enumerate(delta.files, start=1)
    }
    predictions_by_label: dict[str, list[tuple[str, int]]] = {}
    for record in records:
        matching_ops = [
            (operation.method, operation.line)
            for operation in delta.ops
            if file_paths_by_id.get(operation.file_id) == record.file
            and operation.method == record.method
            and record.start_line <= operation.line <= record.end_line
        ]
        predictions_by_label[record.callsite_id] = matching_ops
    return predictions_by_label


def classify_labels_pipeline(
    records: list[LabelRecord],
    predictions_by_label: dict[str, list[tuple[str, int]]],
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Match every label against its file's IR op attribution and count the matrix.

    Same classification semantics as the C-1 measurement (t9/t13), applied
    to the pipeline's per-label ``Op`` attributions instead of C-1 callsites:
    the label's predicted method is the attribution method (identical to the
    label method by construction), and the attributing span is the ``Op``
    line. There is no ``unmatched`` bucket here: ``Op`` rows are produced
    only from labelled-file parses, so every op belongs to a labelled file.
    """
    per_label_rows: list[dict[str, object]] = []
    confusion_counts = {
        "true_positives": 0,
        "false_positives": 0,
        "false_negatives": 0,
        "true_negatives": 0,
    }
    for label in records:
        attributions = predictions_by_label[label.callsite_id]
        predicted = bool(attributions)
        if label.expected_is_redis_callsite and predicted:
            classification = CLASSIFICATION_TRUE_POSITIVE
            confusion_counts["true_positives"] += 1
        elif label.expected_is_redis_callsite:
            classification = CLASSIFICATION_FALSE_NEGATIVE
            confusion_counts["false_negatives"] += 1
        elif predicted:
            classification = CLASSIFICATION_FALSE_POSITIVE
            confusion_counts["false_positives"] += 1
        else:
            classification = CLASSIFICATION_TRUE_NEGATIVE
            confusion_counts["true_negatives"] += 1
        per_label_rows.append({
            "callsite_id": label.callsite_id,
            "file": label.file,
            "span": {
                "start_line": label.start_line,
                "end_line": label.end_line,
            },
            "method": label.method,
            "expected_is_redis_callsite": label.expected_is_redis_callsite,
            "predicted": predicted,
            "predicted_method": attributions[0][0] if attributions else None,
            "predicted_op_line": attributions[0][1] if attributions else None,
            "classification": classification,
        })
    return per_label_rows, confusion_counts


def build_pipeline_block(
    labels_payload: dict[str, object],
    records: list[LabelRecord],
    per_label_rows: list[dict[str, object]],
    confusion_counts: dict[str, int],
    delta: IrDelta,
) -> dict[str, object]:
    """Assemble the additive pipeline measurement block (assignment t14)."""
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
            f"count invariant broken (pipeline): {label_count} labels != "
            f"{true_positives}+{false_positives}+{false_negatives}+{true_negatives} "
            "(TP+FP+FN+TN)"
        )
    positive_count = sum(1 for record in records if record.expected_is_redis_callsite)
    predicted_positive_count = true_positives + false_positives
    if predicted_positive_count == 0:
        precision = 0.0
        precision_note: str | None = (
            "degenerate precision: the full pipeline (C-1 parse -> C-2 IR "
            "ingest) attributed 0 Redis operations to the labelled sample, so "
            "TP + FP == 0 and TP / (TP + FP) is undefined (0/0); recorded as "
            "0.0 with this note, never as a vacuous pass. IR evidence over the "
            f"labelled files: {len(delta.ops)} Op rows, {len(delta.clients)} "
            f"Client rows, {len(delta.unknowns)} unknown entries — the ingest "
            "cycle ran successfully and simply attributes nothing here (see "
            "ir_row_counts and attribution_note); this measures the pipeline's "
            "outcome on the sample, not a measurement failure"
        )
    else:
        precision = compute_precision(true_positives, false_positives)
        precision_note = None
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
        "full pipeline (C-1 parse -> C-2 IR ingest)",
        true_positives,
        false_positives,
        positive_count,
        precision,
        recall,
    )
    verdict = "pass" if precision >= PRECISION_THRESHOLD else "fail"
    require_known_enum(
        verdict, VERDICT_VALUES, f"{RESULT_ARTIFACT}#measurements.pipeline", "verdict"
    )
    return {
        "mode": MODE_PIPELINE,
        "method": "c1_parse_then_ir_ingest",
        "tolerance": TOLERANCE_TEXT,
        "label_count": label_count,
        "positive_label_count": positive_count,
        "negative_label_count": label_count - positive_count,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "true_negatives": true_negatives,
        "precision": precision,
        "precision_note": precision_note,
        "recall": recall,
        "recall_note": recall_note,
        "measurement_interpretation": measurement_interpretation,
        "precision_threshold": PRECISION_THRESHOLD,
        "attribution_note": PIPELINE_ATTRIBUTION_NOTE,
        "ir_row_counts": {
            "ops": len(delta.ops),
            "clients": len(delta.clients),
            "key_exprs": len(delta.key_exprs),
            "unknowns": len(delta.unknowns),
            "scopes": len(delta.scopes),
            "files": len(delta.files),
        },
        "verdict": verdict,
        "per_label": per_label_rows,
    }
