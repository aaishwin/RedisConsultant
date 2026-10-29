"""EXP-2 harness predictions helpers (style contract rule 8).

Split out of evaltools/exp2/harness.py; that module re-exports these names.
"""

from pathlib import Path

from evaltools.exp2.harness_constants import (
    CHECKOUT_ROOT,
)
from evaltools.exp2.harness_labels import LabelRecord
from redis_intel.frontend import LanguageFrontend
from redis_intel.frontend.models import RawRedisCallsite


def checkout_source_path(relative_path: str) -> Path:
    """Resolve a label's repo-relative file inside the pinned checkout.

    Refuses paths that escape the checkout.
    """
    source_path = (CHECKOUT_ROOT / relative_path).resolve()
    if not source_path.is_relative_to(CHECKOUT_ROOT.resolve()):
        raise ValueError(f"label file escapes the pinned checkout: {relative_path!r}")
    if not source_path.is_file():
        raise FileNotFoundError(
            f"labelled file missing from the pinned checkout: {relative_path}"
        )
    return source_path


def collect_predictions_for_labelled_files(
    frontend: LanguageFrontend, labelled_files: list[str]
) -> dict[str, list[RawRedisCallsite]]:
    """Parse each labelled file exactly once and return its extracted callsites."""
    predictions_by_file: dict[str, list[RawRedisCallsite]] = {}
    for relative_path in labelled_files:
        source_path = checkout_source_path(relative_path)
        source = source_path.read_bytes()
        parse_result = frontend.parse(relative_path, source)
        predictions_by_file[relative_path] = list(parse_result.redis_callsites)
    return predictions_by_file


def best_prediction_for_label(
    label: LabelRecord, predictions: list[RawRedisCallsite]
) -> RawRedisCallsite | None:
    """Return the most specific same-method prediction overlapping the label.

    Returns ``None`` when no same-method prediction overlaps.
    """
    same_method_overlapping = [
        prediction
        for prediction in predictions
        if prediction.method == label.method
        and prediction.span.start_line <= label.end_line
        and label.start_line <= prediction.span.end_line
    ]
    if not same_method_overlapping:
        return None
    return min(
        same_method_overlapping,
        key=lambda prediction: (
            prediction.span.end_line - prediction.span.start_line,
            prediction.span.start_line,
            prediction.span.start_col,
        ),
    )
