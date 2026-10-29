"""EXP-2 extraction-precision harness (Contract corpus-and-experiments §3.7/§4).

Parses every labelled file once with ``LanguageFrontend``, matches extracted
callsites to the hand-labelled spans in ``evaltools/exp2/labels.json``, and
computes the confusion matrix and precision in code — never by hand.

Measurement modes (assignment t14):

- ``c1``: the t9/t13 C-1-only measurement — a label is predicted when the
  C-1 extractor emits a same-method ``RawRedisCallsite`` overlapping the
  label span. Unchanged matching semantics; the primary gate measurement.
- ``pipeline``: an additive C-1 → C-2 measurement. Each labelled file is
  parsed with ``LanguageFrontend`` and all parse results are ingested by
  ``IrBuilder().ingest(...)``. A label counts as predicted when the IR
  attributes a Redis operation to that callsite, i.e. when an ``Op`` row's
  ``file_id`` resolves (via the delta's ``FileRow`` tuple) to the label's
  file and ``Op.method`` equals the label's method at a line inside the
  label span. The attribution surface is exactly ``Op.line`` (copied from
  ``callsite.span.start_line`` by ``_emit_op_and_key_expr``) plus
  ``Op.file_id``/``Op.method`` — no heuristic mapping is invented. When the
  ingest cycle produces no attribution row for any label the measurement
  still runs and records its real (degenerate) counts with a note naming
  the IR evidence: it measures "the pipeline attributes nothing here", not
  a measurement failure.
- ``both``: run both measurements, write both blocks into
  ``results/exp2.json`` under ``measurements.c1_only`` and
  ``measurements.pipeline`` (each with its own per_label rows, confusion
  counts, precision, threshold judgement and code-computed verdict), keep
  every existing top-level field pointing at the primary ``c1_only``
  measurement, and record the choice in ``measurement_scope_note``. The
  gate is never re-pointed at the better-looking number.

The IR evidence trail for the ``pipeline`` attribution surface is recorded
in each result block under ``attribution_note``; when the IR carries zero
``Op`` rows over the labelled files the block also carries
``ir_row_counts`` so the degenerate outcome is auditable from the file.

Matching semantics (kept minimal by assignment t9):

- A prediction matches a label when both point at the same file, their
  line spans overlap, and the predicted method equals the labelled method.
  Among equally-methoded overlapping predictions the smallest span wins
  (most specific call), tie-broken by start position — deterministic.
- true_positive  = positive label matched by a prediction.
- false_negative = positive label with no matching prediction.
- false_positive = negative label matched by a prediction (the extractor
  flagged a hand-verified non-Redis call).
- true_negative  = negative label with no matching prediction.
- Predictions overlapping no label at all are counted separately as
  ``unmatched_prediction_count`` and never enter the confusion matrix: the
  label set is a deliberate sample (see ``sampling_rule`` in labels.json),
  so a correct detection outside the sample is not an error. Precision is
  therefore TP / (TP + FP) over the labelled sample.

Recall and interpretation (t13 re-measure): each measurement block also
computes recall = TP / (TP + FN) in code alongside precision, and a
``measurement_interpretation`` note that states in words whether the
precision figure rests on enough matched predictions to mean anything
(a precision over a near-empty match set against a 38-positive label
sample does not demonstrate NFR-2's intent even when it is 1.0).

Degenerate denominator (t13): when the extractor predicts nothing over the
labelled sample (TP + FP == 0) precision is undefined (0/0). The run still
writes its result file — a missing result file is never a valid outcome
(Contract §4) — recording precision ``0.0`` with a ``precision_note`` naming
the degenerate denominator, and the verdict is computed from that precision
as usual (``0.0 < 0.80`` ⇒ ``fail``). Zero is chosen over a vacuous 1.0
because the gate "precision ≥ 0.80" is undemonstrated, never silently passed;
the note prevents reading 0.0 as "every prediction was wrong".

The count invariant ``label_count == TP + FP + FN + TN`` is asserted before
the result file is written. The verdict is computed from the 0.80 precision
threshold; the advisory measurement environment can never convert a fail
into a pass because the verdict depends only on the computed precision
(Contract §4).
"""

import argparse

from evaltools.exp2.harness_classify import (
    classify_labels,
    compute_precision,
    compute_recall,
)
from evaltools.exp2.harness_cli import (
    print_measurement_summary,
    print_per_label_table,
    print_pipeline_table,
)
from evaltools.exp2.harness_constants import (
    CHECKOUT_ROOT,
    LABELS_PATH,
    MODE_BOTH,
    MODE_C1,
    MODE_PIPELINE,
    MODE_VALUES,
    PIPELINE_MEASUREMENT_KEY,
    PRIMARY_MEASUREMENT_KEY,
    RESULT_PATH,
)
from evaltools.exp2.harness_labels import (
    LabelRecord,
    load_label_records,
    parse_label_entry,
)
from evaltools.exp2.harness_payload import (
    build_measurement_interpretation,
    build_result_payload,
)
from evaltools.exp2.harness_pipeline import (
    build_pipeline_block,
    classify_labels_pipeline,
    pipeline_predictions_by_label,
)
from evaltools.exp2.harness_predictions import (
    best_prediction_for_label,
    checkout_source_path,
    collect_predictions_for_labelled_files,
)
from evaltools.exp2.harness_run import run_experiment

__all__ = [
    "CHECKOUT_ROOT",
    "LABELS_PATH",
    "RESULT_PATH",
    "LabelRecord",
    "best_prediction_for_label",
    "build_measurement_interpretation",
    "build_pipeline_block",
    "build_result_payload",
    "checkout_source_path",
    "classify_labels",
    "classify_labels_pipeline",
    "collect_predictions_for_labelled_files",
    "compute_precision",
    "compute_recall",
    "load_label_records",
    "main",
    "parse_label_entry",
    "pipeline_predictions_by_label",
    "run_experiment",
]


def main() -> int:
    """CLI entry point: run the experiment in --mode, print tables and summaries."""
    parser = argparse.ArgumentParser(
        description="EXP-2 extraction-precision harness (modes: c1, pipeline, both)"
    )
    parser.add_argument(
        "--mode",
        choices=MODE_VALUES,
        default=MODE_BOTH,
        help=(
            "c1 = C-1-only extraction measurement (t9/t13 gate); pipeline = "
            "additive C-1 parse -> C-2 IR ingest measurement; both = write both "
            "blocks (default)"
        ),
    )
    arguments = parser.parse_args()
    result_payload = run_experiment(mode=arguments.mode)
    if arguments.mode == MODE_C1:
        print_per_label_table(result_payload)
        print_measurement_summary(result_payload, MODE_C1)
    elif arguments.mode == MODE_PIPELINE:
        measurements = result_payload["measurements"]
        if not isinstance(measurements, dict):
            raise TypeError("measurements must be a JSON object")
        pipeline_block = measurements[PIPELINE_MEASUREMENT_KEY]
        if not isinstance(pipeline_block, dict):
            raise TypeError("pipeline measurement block must be a JSON object")
        print_pipeline_table(pipeline_block)
        print_measurement_summary(pipeline_block, MODE_PIPELINE)
        ir_row_counts = pipeline_block.get("ir_row_counts")
        if isinstance(ir_row_counts, dict):
            print(f"ir_row_counts: {ir_row_counts}")
    else:
        measurements = result_payload["measurements"]
        if not isinstance(measurements, dict):
            raise TypeError("measurements must be a JSON object")
        c1_block = measurements[PRIMARY_MEASUREMENT_KEY]
        pipeline_block = measurements[PIPELINE_MEASUREMENT_KEY]
        if not isinstance(c1_block, dict) or not isinstance(pipeline_block, dict):
            raise TypeError("measurement blocks must be JSON objects")
        print("[c1_only — primary gate measurement]")
        print_per_label_table(c1_block)
        print_measurement_summary(c1_block, PRIMARY_MEASUREMENT_KEY)
        print()
        print("[pipeline — additive C-1 -> C-2 IR measurement]")
        print_pipeline_table(pipeline_block)
        print_measurement_summary(pipeline_block, PIPELINE_MEASUREMENT_KEY)
    print("-" * 80)
    print(f"mode: {arguments.mode}")
    scope_note = result_payload.get("measurement_scope_note")
    if isinstance(scope_note, str):
        print(f"measurement_scope_note: {scope_note}")
    print(f"result file: {RESULT_PATH}")
    return 0
