"""EXP-2 harness labels helpers (style contract rule 8).

Split out of evaltools/exp2/harness.py; that module re-exports these names.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from evaltools.exp2.harness_constants import (
    LABELS_SCHEMA_VERSION,
)
from evaltools.gate_evidence import (
    require_schema_version,
)


@dataclass(frozen=True)
class LabelRecord:
    """One hand-labelled callsite, validated at the boundary."""

    callsite_id: str
    file: str
    start_line: int
    end_line: int
    method: str
    expected_is_redis_callsite: bool
    raw: dict[str, object]


def load_label_records(path: Path) -> tuple[dict[str, object], list[LabelRecord]]:
    """Load and validate the frozen label set; fail fast on any contract breach."""
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as load_error:
        raise RuntimeError(
            f"cannot load label file {path}: {load_error}"
        ) from load_error
    require_schema_version(payload, LABELS_SCHEMA_VERSION)
    entries = payload["entries"]
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path}: 'entries' must be a non-empty array")
    records = [parse_label_entry(entry, path) for entry in entries]
    identifiers = [record.callsite_id for record in records]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{path}: duplicate callsite_id values in the label set")
    return payload, records


def parse_label_entry(entry: object, path: Path) -> LabelRecord:
    """Validate one label entry against the label-schema shape."""
    if not isinstance(entry, dict):
        raise TypeError(f"{path}: label entries must be JSON objects")
    span = entry.get("span")
    if not isinstance(span, dict):
        raise TypeError(
            f"{path}: label {entry.get('callsite_id')!r} has no span object"
        )
    start_line = span.get("start_line")
    end_line = span.get("end_line")
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        raise TypeError(
            f"{path}: label {entry.get('callsite_id')!r} has non-integer span lines"
        )
    expected_flag = entry.get("expected_is_redis_callsite")
    if not isinstance(expected_flag, bool):
        raise TypeError(
            f"{path}: label {entry.get('callsite_id')!r} has non-boolean "
            "'expected_is_redis_callsite'"
        )
    callsite_id = entry.get("callsite_id")
    file_path = entry.get("file")
    method = entry.get("method")
    if (
        not isinstance(callsite_id, str)
        or not isinstance(file_path, str)
        or not isinstance(method, str)
    ):
        raise TypeError(f"{path}: label with non-string callsite_id/file/method")
    return LabelRecord(
        callsite_id=callsite_id,
        file=file_path,
        start_line=start_line,
        end_line=end_line,
        method=method,
        expected_is_redis_callsite=expected_flag,
        raw=entry,
    )
