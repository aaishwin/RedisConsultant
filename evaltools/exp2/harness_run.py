"""EXP-2 harness run helpers (style contract rule 8).

Split out of evaltools/exp2/harness.py; that module re-exports these names.
"""

from pathlib import Path

from evaltools.exp2.harness_classify import classify_labels
from evaltools.exp2.harness_constants import (
    LABELS_PATH,
    MODE_BOTH,
    MODE_C1,
    MODE_PIPELINE,
    MODE_VALUES,
    PIPELINE_MEASUREMENT_KEY,
    PRIMARY_MEASUREMENT_KEY,
    RESULT_ARTIFACT,
    RESULT_PATH,
    RESULT_SCHEMA_VERSION,
)
from evaltools.exp2.harness_labels import load_label_records
from evaltools.exp2.harness_payload import build_result_payload
from evaltools.exp2.harness_pipeline import (
    build_pipeline_block,
    classify_labels_pipeline,
    pipeline_predictions_by_label,
)
from evaltools.exp2.harness_predictions import (
    checkout_source_path,
    collect_predictions_for_labelled_files,
)
from evaltools.gate_evidence import (
    require_known_enum,
    write_result_json,
)
from redis_intel.frontend import LanguageFrontend
from redis_intel.frontend.models import ParseResult
from redis_intel.ir import IrBuilder


def run_experiment(
    labels_path: Path = LABELS_PATH,
    result_path: Path = RESULT_PATH,
    mode: str = MODE_BOTH,
) -> dict[str, object]:
    """Run the EXP-2 measurement in the requested mode and write the result file."""
    require_known_enum(mode, MODE_VALUES, RESULT_ARTIFACT, "mode")
    labels_payload, records = load_label_records(labels_path)
    frontend = LanguageFrontend()
    labelled_files = sorted({record.file for record in records})

    result_payload: dict[str, object] | None = None
    measurements: dict[str, object] = {}

    if mode in (MODE_C1, MODE_BOTH):
        predictions_by_file = collect_predictions_for_labelled_files(
            frontend, labelled_files
        )
        per_label_rows, confusion_counts, unmatched_prediction_count = classify_labels(
            records, predictions_by_file
        )
        result_payload = build_result_payload(
            labels_payload,
            records,
            per_label_rows,
            confusion_counts,
            unmatched_prediction_count,
        )
        if mode == MODE_C1:
            write_result_json(result_path, result_payload)
            return result_payload
        measurements[PRIMARY_MEASUREMENT_KEY] = result_payload

    if mode in (MODE_PIPELINE, MODE_BOTH):
        parse_results: list[ParseResult] = []
        for relative_path in labelled_files:
            source_path = checkout_source_path(relative_path)
            parse_results.append(
                frontend.parse(relative_path, source_path.read_bytes())
            )
        delta = IrBuilder.ingest(parse_results)
        pipeline_predictions = pipeline_predictions_by_label(delta, records)
        pipeline_rows, pipeline_counts = classify_labels_pipeline(
            records, pipeline_predictions
        )
        measurements[PIPELINE_MEASUREMENT_KEY] = build_pipeline_block(
            labels_payload, records, pipeline_rows, pipeline_counts, delta
        )

    combined_payload: dict[str, object] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "artifact": RESULT_ARTIFACT,
        "repo": "bullmq",
        "commit_sha": labels_payload["pinned_sha"],
        "pinned_sha": labels_payload["pinned_sha"],
        "pinned_tag": labels_payload["pinned_tag"],
        "measurement_scope_note": (
            "primary measurement is c1_only (the t9/t13 C-1-only extraction "
            "gate; all pre-existing top-level fields mirror that block and the "
            "0.80 precision gate is judged on it); the pipeline block is an "
            "additive C-1 parse -> C-2 IR ingest measurement of the same frozen "
            "labels recorded so the lead can decide what the gate measures — "
            "the gate has NOT been re-pointed at the better-looking number"
        )
        if mode != MODE_PIPELINE
        else (
            "pipeline-only run: the c1_only block was not computed in this mode, "
            "so the shared top-level fields mirror the pipeline block; run "
            "--mode both for the primary c1_only gate measurement"
        ),
        "measurements": measurements,
    }
    if mode == MODE_PIPELINE:
        # Pipeline-only run: there is no c1_only block to mirror, so the shared
        # top-level fields mirror the pipeline block instead.
        source_block = measurements[PIPELINE_MEASUREMENT_KEY]
        if not isinstance(source_block, dict):
            raise TypeError("pipeline measurement block must be a JSON object")
        top_level_fields: tuple[str, ...] = (
            "method",
            "tolerance",
            "label_count",
            "positive_label_count",
            "negative_label_count",
            "true_positives",
            "false_positives",
            "false_negatives",
            "true_negatives",
            "precision",
            "precision_note",
            "recall",
            "recall_note",
            "measurement_interpretation",
            "precision_threshold",
            "verdict",
            "per_label",
        )
    else:
        source_block = measurements[PRIMARY_MEASUREMENT_KEY]
        if not isinstance(source_block, dict):
            raise TypeError("c1_only measurement block must be a JSON object")
        top_level_fields = (
            "method",
            "tolerance",
            "label_count",
            "positive_label_count",
            "negative_label_count",
            "true_positives",
            "false_positives",
            "false_negatives",
            "true_negatives",
            "unmatched_prediction_count",
            "matching_note",
            "precision",
            "precision_note",
            "recall",
            "recall_note",
            "measurement_interpretation",
            "precision_threshold",
            "measurement_environment",
            "verdict",
            "fetch_command",
            "per_label",
        )
    for field_name in top_level_fields:
        combined_payload[field_name] = source_block[field_name]
    write_result_json(result_path, combined_payload)
    return combined_payload
