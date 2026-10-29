"""Constants shared by the EXP-2 harness modules (style contract rule 8)."""

from pathlib import Path

from evaltools.gate_evidence import SCHEMA_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]


CHECKOUT_ROOT = REPO_ROOT / "corpora" / "upstream" / "bullmq"


LABELS_PATH = REPO_ROOT / "evaltools" / "exp2" / "labels.json"


RESULT_PATH = REPO_ROOT / "results" / "exp2.json"


LABELS_SCHEMA_VERSION = "exp2-labels 0.1.0"


RESULT_ARTIFACT = "results/exp2.json"


RESULT_SCHEMA_VERSION = SCHEMA_VERSION


VERDICT_VALUES = ("pass", "fail", "blocked-pending-corpus")


PRECISION_THRESHOLD = 0.80


TOLERANCE_TEXT = (
    "exact per-callsite match on resolved_depth and tier; template_correct must match"
)


MODE_VALUES = ("c1", "pipeline", "both")


MODE_C1 = "c1"


MODE_PIPELINE = "pipeline"


MODE_BOTH = "both"


PRIMARY_MEASUREMENT_KEY = "c1_only"


PIPELINE_MEASUREMENT_KEY = "pipeline"


PIPELINE_ATTRIBUTION_NOTE = (
    "attribution surface: an Op row attributes a Redis operation to a label "
    "when Op.file_id resolves to the label file via the delta's FileRow.path, "
    "Op.method equals the label method, and Op.line falls inside the label "
    "span; Op.line is callsite.span.start_line as emitted by "
    "ir.builder._emit_op_and_key_expr — no heuristic mapping is invented"
)


CLASSIFICATION_TRUE_POSITIVE = "true_positive"


CLASSIFICATION_FALSE_POSITIVE = "false_positive"


CLASSIFICATION_FALSE_NEGATIVE = "false_negative"


CLASSIFICATION_TRUE_NEGATIVE = "true_negative"
