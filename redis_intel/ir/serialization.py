"""Canonical JSONL serialization and deserialization of IrDelta (§4.5).

Format: UTF-8, LF line endings. First line ``# ir_schema_version: <version>``,
then one block per collection in the fixed kind order of contract section 4.2.
Each block begins with a ``# kind`` header line (e.g. ``# clients``), followed
by one row-object per line in the block's natural key order, each canonically
dumped (``json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=True)``). ``deserialize`` fails hard on a missing/unknown
``# kind`` header, an out-of-enum value, a ``schema_version`` mismatch, or a
dangling logical id (contract section 4.5 round-trip policy).
"""

import json
from dataclasses import fields
from typing import Any

from redis_intel.ir.models import (
    CLIENT_LIBRARIES,
    EDGE_TYPES,
    EPISTEMIC_TIERS,
    GRAMMAR_IDS,
    IR_SCHEMA_VERSION,
    KEY_EXPR_KINDS,
    NODE_KINDS,
    OP_KINDS,
    REVISION_KINDS,
    SCOPE_KINDS,
    SERIALIZER_METHODS,
    SYMBOL_KINDS,
    UNKNOWN_REASONS,
    Client,
    Edge,
    FileRow,
    IrDelta,
    KeyExpr,
    Namespace,
    Op,
    Revision,
    Scope,
    Serializer,
    Symbol,
    Tombstone,
    TtlSource,
    UnknownEntry,
)
from redis_intel.ir.serialization_validation import (
    build_ir_delta as _build_ir_delta,
)

_BLOCK_ORDER: tuple[str, ...] = (
    "revisions",
    "files",
    "scopes",
    "symbols",
    "clients",
    "ops",
    "key_exprs",
    "namespaces",
    "serializers",
    "ttl_sources",
    "edges",
    "unknowns",
    "tombstones",
)

_ENUM_VALIDATORS: dict[str, tuple[str, ...]] = {
    "revision.kind": REVISION_KINDS,
    "file.grammar_id": GRAMMAR_IDS,
    "scope.kind": SCOPE_KINDS,
    "scope.epistemic": EPISTEMIC_TIERS,
    "symbol.kind": SYMBOL_KINDS,
    "symbol.epistemic": EPISTEMIC_TIERS,
    "client.client_library": CLIENT_LIBRARIES,
    "client.epistemic": EPISTEMIC_TIERS,
    "op.kind": OP_KINDS,
    "op.epistemic": EPISTEMIC_TIERS,
    "key_expr.kind": KEY_EXPR_KINDS,
    "key_expr.epistemic": EPISTEMIC_TIERS,
    "namespace.epistemic": EPISTEMIC_TIERS,
    "serializer.method": SERIALIZER_METHODS,
    "serializer.epistemic": EPISTEMIC_TIERS,
    "ttl_source.epistemic": EPISTEMIC_TIERS,
    "edge.source_kind": NODE_KINDS,
    "edge.edge_type": EDGE_TYPES,
    "edge.target_kind": NODE_KINDS,
    "edge.epistemic": EPISTEMIC_TIERS,
    "unknown.reason": UNKNOWN_REASONS,
    "unknown.subject_kind": (
        "file",
        "scope",
        "callsite",
        "key_expr",
        "client",
        "op",
        "symbol",
    ),
}


def serialize(delta: IrDelta) -> bytes:
    """Serialize ``delta`` into canonical JSONL bytes (contract section 4.5)."""
    if delta.schema_version != IR_SCHEMA_VERSION:
        raise ValueError(
            f"cannot serialize an IrDelta whose schema_version "
            f"{delta.schema_version!r} differs from the current {IR_SCHEMA_VERSION!r}"
        )
    lines: list[str] = [f"# ir_schema_version: {IR_SCHEMA_VERSION}"]
    for block_kind in _BLOCK_ORDER:
        collection = getattr(delta, block_kind)
        lines.append(f"# {block_kind}")
        for row in collection:
            lines.append(
                json.dumps(
                    _row_to_dict(block_kind, row),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
            )
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def deserialize(data: bytes) -> IrDelta:
    """Parse canonical JSONL bytes back into an :class:`IrDelta`."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"serialized IR is not valid UTF-8: {error}") from error
    lines = text.splitlines()
    if not lines:
        raise ValueError("serialized IR is empty")
    if not lines[0].startswith("# ir_schema_version: "):
        raise ValueError(
            f"first line must be a schema-version header, got {lines[0]!r}"
        )
    schema_version = lines[0].removeprefix("# ir_schema_version: ").strip()
    if schema_version != IR_SCHEMA_VERSION:
        raise ValueError(

                f"schema_version {schema_version!r} is not the current"
                f" {IR_SCHEMA_VERSION!r}"

        )
    blocks = _parse_blocks(lines[1:])
    return _ir_delta_from_blocks(blocks)


def _row_to_dict(block_kind: str, row: Any) -> dict[str, Any]:
    row_fields = fields(row)
    if len(row_fields) == 0:
        raise ValueError(f"cannot serialize {block_kind!r} row with no fields")
    row_dict = {field.name: getattr(row, field.name) for field in row_fields}
    return _normalize_nested_collections(row_dict)


def _normalize_nested_collections(row_dict: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for field_name, value in row_dict.items():
        if isinstance(value, tuple):
            normalized[field_name] = list(value)
        elif isinstance(value, list):
            normalized[field_name] = [
                _normalize_nested_collections(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            normalized[field_name] = value
    return normalized


def _parse_blocks(lines: list[str]) -> dict[str, list[str]]:
    """Group raw JSONL lines by their ``# kind`` header, in file order."""
    blocks: dict[str, list[str]] = {}
    current_kind: str | None = None
    previous_block_index = -1
    for line in lines:
        if line.startswith("# "):
            block_kind = line[2:].strip()
            if block_kind not in _BLOCK_ORDER:
                raise ValueError(f"unknown or missing block kind header {block_kind!r}")
            if block_kind in blocks:
                raise ValueError(f"block kind {block_kind!r} appears more than once")
            block_index = _BLOCK_ORDER.index(block_kind)
            if block_index != previous_block_index + 1:
                raise ValueError(
                    f"block {block_kind!r} is out of the fixed kind order "
                    f"(expected next: {_BLOCK_ORDER[previous_block_index + 1]!r})"
                )
            previous_block_index = block_index
            current_kind = block_kind
            blocks[current_kind] = []
            continue
        if current_kind is None:
            raise ValueError(f"row appears before any '# kind' header: {line!r}")
        if line.strip():
            blocks[current_kind].append(line)
    for block_kind in _BLOCK_ORDER:
        if block_kind not in blocks:
            raise ValueError(f"missing block kind header for {block_kind!r}")
    return blocks


def _ir_delta_from_blocks(blocks: dict[str, list[str]]) -> IrDelta:
    parsed_rows = {
        block_kind: [_parse_row(block_kind, line) for line in block_lines]
        for block_kind, block_lines in blocks.items()
    }
    return _build_ir_delta(parsed_rows)


def _parse_row(block_kind: str, line: str) -> Any:
    try:
        row_dict = json.loads(line)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"malformed JSON line in {block_kind!r} block: {error}"
        ) from error
    if not isinstance(row_dict, dict):
        raise TypeError(f"row in {block_kind!r} block is not a JSON object: {line!r}")
    _validate_enums(block_kind, row_dict)
    return _construct_row(block_kind, row_dict)


def _validate_enums(block_kind: str, row_dict: dict[str, Any]) -> None:
    for enum_key, allowed_values in _ENUM_VALIDATORS.items():
        enum_field_name = enum_key.split(".")[1]
        if block_kind != enum_key.split(".")[0] or enum_field_name not in row_dict:
            continue
        actual_value = row_dict[enum_field_name]
        if actual_value not in allowed_values:
            raise ValueError(

                    f"{enum_field_name} value {actual_value!r} in {block_kind!r}"
                    f" block is not one of {allowed_values}"

            )


def _construct_row(block_kind: str, row_dict: dict[str, Any]) -> Any:
    if block_kind == "revisions":
        return Revision(**row_dict)
    if block_kind == "files":
        return FileRow(**row_dict)
    if block_kind == "scopes":
        return Scope(**row_dict)
    if block_kind == "symbols":
        return Symbol(**row_dict)
    if block_kind == "clients":
        return Client(**row_dict)
    if block_kind == "ops":
        args_values = row_dict.pop("args", ())
        return Op(args=tuple(args_values), **row_dict)
    if block_kind == "key_exprs":
        slots_values = row_dict.pop("slots", ())
        return KeyExpr(slots=tuple(slots_values), **row_dict)
    if block_kind == "namespaces":
        return Namespace(**row_dict)
    if block_kind == "serializers":
        return Serializer(**row_dict)
    if block_kind == "ttl_sources":
        return TtlSource(**row_dict)
    if block_kind == "edges":
        return Edge(**row_dict)
    if block_kind == "unknowns":
        span = row_dict.pop("span", None)
        return UnknownEntry(span=tuple(span) if span is not None else None, **row_dict)
    if block_kind == "tombstones":
        return Tombstone(**row_dict)
    raise ValueError(f"cannot construct a row for unknown block kind {block_kind!r}")
