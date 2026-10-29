"""Shared result-file helpers for the gate-evidence pipeline.

Contract 2 §1/§6: every result artifact carries
``schema_version = "eval-schema 0.1.1"``; readers fail fast on an unknown enum
value or an incompatible schema version,
naming the artifact and the offending value instead of logging and continuing.
Writes are atomic (temp file in the destination directory, then ``os.replace``)
so a crashed run can never leave a truncated result file for the gates.
"""

import json
import os
from collections.abc import Collection, Mapping
from pathlib import Path

SCHEMA_VERSION = "eval-schema 0.1.1"


def require_schema_version(payload: Mapping[str, object], expected: str) -> None:
    """Fail fast unless the payload declares exactly the expected schema version.

    The error names the artifact (its ``artifact`` field, else ``schema_version``)
    and the offending value so a stale or mislabeled result file is caught at the
    boundary, never passed along to the gates.
    """
    if "schema_version" not in payload:
        raise ValueError("payload is missing the required field 'schema_version'")
    actual_version = payload["schema_version"]
    if actual_version != expected:
        artifact_name = payload.get("artifact", "schema_version")
        raise ValueError(
            f"artifact {artifact_name!r}: incompatible schema_version "
            f"{actual_version!r}; expected {expected!r}"
        )


def require_known_enum(
    value: str, allowed: Collection[str], artifact: str, field: str
) -> None:
    """Fail fast unless ``value`` is one of the allowed enum members.

    The error names the artifact, the field and the offending value so an
    unexpected label or verdict can never silently flow downstream.
    """
    if value not in allowed:
        raise ValueError(
            f"artifact {artifact!r}: unknown value {value!r} for field {field!r}; "
            f"allowed values: {sorted(allowed)}"
        )


def write_result_json(path: str | Path, payload: Mapping[str, object]) -> Path:
    """Serialize ``payload`` as pretty JSON and write it atomically to ``path``.

    The destination directory is created if missing. The payload is first written
    to a temp file in the same directory, flushed to disk, then moved into place
    with ``os.replace`` — the same-directory temp file keeps the rename atomic on
    both darwin and linux, and readers never observe a partial result file.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(f"{destination.name}.tmp")
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    try:
        with open(temporary_path, "w", encoding="utf-8") as handle:
            handle.write(serialized + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    except BaseException as write_error:
        _remove_failed_temporary_file(destination, temporary_path, write_error)
        raise
    return destination


def _remove_failed_temporary_file(
    destination: Path, temporary_path: Path, write_error: BaseException
) -> None:
    """Best-effort cleanup that still surfaces a failed temp-file removal."""
    try:
        os.unlink(temporary_path)
    except OSError as cleanup_error:
        raise RuntimeError(
            f"result write to {destination} failed ({write_error}); additionally "
            f"failed to remove temporary file {temporary_path}: {cleanup_error}"
        ) from write_error


def load_result_json(path: str | Path) -> dict[str, object]:
    """Load a result file written by ``write_result_json`` and return its mapping."""
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot load result file {path}: {error}") from error
    if not isinstance(loaded, dict):
        raise ValueError(
            f"{path}: expected a JSON object, found {type(loaded).__name__}"
        )
    return loaded
