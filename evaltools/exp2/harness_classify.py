"""EXP-2 harness classify helpers (style contract rule 8).

Split out of evaltools/exp2/harness.py; that module re-exports these names.
"""


from evaltools.exp2.harness_constants import (
    CLASSIFICATION_FALSE_NEGATIVE,
    CLASSIFICATION_FALSE_POSITIVE,
    CLASSIFICATION_TRUE_NEGATIVE,
    CLASSIFICATION_TRUE_POSITIVE,
)
from evaltools.exp2.harness_labels import LabelRecord
from evaltools.exp2.harness_predictions import best_prediction_for_label
from redis_intel.frontend.models import RawRedisCallsite


def classify_labels(
    records: list[LabelRecord], predictions_by_file: dict[str, list[RawRedisCallsite]]
) -> tuple[list[dict[str, object]], dict[str, int], int]:
    """Match labels against predictions and count the confusion matrix."""
    per_label_rows: list[dict[str, object]] = []
    confusion_counts = {
        "true_positives": 0,
        "false_positives": 0,
        "false_negatives": 0,
        "true_negatives": 0,
    }
    matched_prediction_indexes: dict[str, set[int]] = {
        relative_path: set() for relative_path in predictions_by_file
    }
    for label in records:
        predictions = predictions_by_file[label.file]
        best_prediction = best_prediction_for_label(label, predictions)
        predicted = best_prediction is not None
        if predicted and best_prediction is not None:
            matched_prediction_indexes[label.file].add(
                predictions.index(best_prediction)
            )
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
            "predicted_method": (
                best_prediction.method if best_prediction is not None else None
            ),
            "predicted_client_hint": (
                best_prediction.client_hint if best_prediction is not None else None
            ),
            "classification": classification,
        })
    unmatched_prediction_count = sum(
        len(predictions) - len(matched_prediction_indexes[relative_path])
        for relative_path, predictions in predictions_by_file.items()
    )
    return per_label_rows, confusion_counts, unmatched_prediction_count


def compute_precision(true_positives: int, false_positives: int) -> float:
    """Compute labelled-sample precision; the caller must exclude the 0/0 case."""
    denominator = true_positives + false_positives
    if denominator == 0:
        raise ValueError(
            "compute_precision requires a non-zero denominator; handle the "
            "degenerate TP+FP==0 case at the result-assembly site"
        )
    return true_positives / denominator


def compute_recall(true_positives: int, false_negatives: int) -> float:
    """Compute labelled-sample recall; the caller must exclude the 0/0 case."""
    denominator = true_positives + false_negatives
    if denominator == 0:
        raise ValueError(
            "compute_recall requires a non-zero denominator; handle the "
            "degenerate TP+FN==0 case at the result-assembly site"
        )
    return true_positives / denominator
