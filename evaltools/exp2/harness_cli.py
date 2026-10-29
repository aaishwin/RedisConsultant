"""EXP-2 harness cli helpers (style contract rule 8).

Split out of evaltools/exp2/harness.py; that module re-exports these names.
"""


def print_per_label_table(result_payload: dict[str, object]) -> None:
    """Print the per-label table for whichever measurement block is requested."""
    per_label_rows = result_payload["per_label"]
    if not isinstance(per_label_rows, list):
        raise TypeError("result payload 'per_label' must be an array")
    header = (
        f"{'id':7} {'file':42} {'span':12} {'method':16} "
        f"{'expected':9} {'predicted':9} {'client_hint':12} class"
    )
    print(header)
    print("-" * len(header))
    for row in per_label_rows:
        if not isinstance(row, dict):
            raise TypeError("result payload 'per_label' rows must be JSON objects")
        span_text = f"{row['span']['start_line']}-{row['span']['end_line']}"
        expected_text = "redis" if row["expected_is_redis_callsite"] else "not-redis"
        predicted_text = "yes" if row["predicted"] else "no"
        client_hint = row["predicted_client_hint"] or "-"
        print(
            f"{row['callsite_id']:7} {row['file']:42} {span_text:12} "
            f"{row['method']:16} {expected_text:9} {predicted_text:9} "
            f"{client_hint:12} {row['classification']}"
        )


def print_pipeline_table(pipeline_block: dict[str, object]) -> None:
    """Print the pipeline per-label table (file, span, method, expected, IR)."""
    per_label_rows = pipeline_block["per_label"]
    if not isinstance(per_label_rows, list):
        raise TypeError("pipeline block 'per_label' must be an array")
    header = (
        f"{'id':7} {'file':42} {'span':12} {'method':16} "
        f"{'expected':9} {'predicted':9} {'ir_op_line':10} class"
    )
    print(header)
    print("-" * len(header))
    for row in per_label_rows:
        if not isinstance(row, dict):
            raise TypeError("pipeline block 'per_label' rows must be JSON objects")
        span_text = f"{row['span']['start_line']}-{row['span']['end_line']}"
        expected_text = "redis" if row["expected_is_redis_callsite"] else "not-redis"
        predicted_text = "yes" if row["predicted"] else "no"
        op_line_text = (
            str(row["predicted_op_line"]) if row["predicted_op_line"] else "-"
        )
        print(
            f"{row['callsite_id']:7} {row['file']:42} {span_text:12} "
            f"{row['method']:16} {expected_text:9} {predicted_text:9} "
            f"{op_line_text:10} {row['classification']}"
        )


def print_measurement_summary(block: dict[str, object], title: str) -> None:
    """Print one measurement block's confusion counts, precision and verdict."""
    summary_fields = (
        "label_count",
        "true_positives",
        "false_positives",
        "false_negatives",
        "true_negatives",
        "precision",
        "recall",
        "precision_threshold",
        "verdict",
    )
    print("-" * 80)
    print(f"[{title}]")
    for field_name in summary_fields:
        print(f"{field_name}: {block[field_name]}")
