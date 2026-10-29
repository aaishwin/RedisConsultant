"""Logical-id reference validation and IrDelta assembly for the C-2 serializer.

Split out of :mod:`redis_intel.ir.serialization` so that module stays inside
the repository's 250-code-line limit (style contract rule 8).
"""

from typing import Any

from redis_intel.ir.models import IR_SCHEMA_VERSION, IrDelta


def build_ir_delta(parsed_rows: dict[str, list[Any]]) -> IrDelta:
    validate_logical_id_references(parsed_rows)
    return IrDelta(
        schema_version=IR_SCHEMA_VERSION,
        revisions=tuple(parsed_rows.get("revisions", ())),
        files=tuple(parsed_rows.get("files", ())),
        scopes=tuple(parsed_rows.get("scopes", ())),
        symbols=tuple(parsed_rows.get("symbols", ())),
        clients=tuple(parsed_rows.get("clients", ())),
        ops=tuple(parsed_rows.get("ops", ())),
        key_exprs=tuple(parsed_rows.get("key_exprs", ())),
        namespaces=tuple(parsed_rows.get("namespaces", ())),
        serializers=tuple(parsed_rows.get("serializers", ())),
        ttl_sources=tuple(parsed_rows.get("ttl_sources", ())),
        edges=tuple(parsed_rows.get("edges", ())),
        unknowns=tuple(parsed_rows.get("unknowns", ())),
        tombstones=tuple(parsed_rows.get("tombstones", ())),
    )


def validate_logical_id_references(parsed_rows: dict[str, list[Any]]) -> None:
    """Fail fast on dangling logical ids (contract section 4.5).

    Every integer id reference (file_id, scope_id, client_id, key_expr_id,
    ttl_source_id, op_id, edge endpoints) must fall inside the 1..n range of
    its target collection. Row order is trusted to be natural-key order, so
    id i refers to row i-1 of the same kind.
    """
    collection_sizes = {
        "files": len(parsed_rows.get("files", ())),
        "scopes": len(parsed_rows.get("scopes", ())),
        "symbols": len(parsed_rows.get("symbols", ())),
        "clients": len(parsed_rows.get("clients", ())),
        "ops": len(parsed_rows.get("ops", ())),
        "key_exprs": len(parsed_rows.get("key_exprs", ())),
        "serializers": len(parsed_rows.get("serializers", ())),
        "namespaces": len(parsed_rows.get("namespaces", ())),
        "ttl_sources": len(parsed_rows.get("ttl_sources", ())),
    }
    # Edges and tombstones reference node kinds (singular, e.g. "file"), so
    # map each node kind onto its plural collection size.
    node_kind_sizes = {
        "file": collection_sizes["files"],
        "scope": collection_sizes["scopes"],
        "symbol": collection_sizes["symbols"],
        "client": collection_sizes["clients"],
        "op": collection_sizes["ops"],
        "key_expr": collection_sizes["key_exprs"],
        "namespace": collection_sizes["namespaces"],
        "serializer": collection_sizes["serializers"],
        "ttl_source": collection_sizes["ttl_sources"],
    }
    for scope_row in parsed_rows.get("scopes", ()):
        require_logical_id(
            scope_row.file_id, collection_sizes["files"], "file_id", "scopes"
        )
    for symbol_row in parsed_rows.get("symbols", ()):
        require_logical_id(
            symbol_row.file_id, collection_sizes["files"], "file_id", "symbols"
        )
        if symbol_row.scope_id is not None:
            require_logical_id(
                symbol_row.scope_id, collection_sizes["scopes"], "scope_id", "symbols"
            )
    for client_row in parsed_rows.get("clients", ()):
        require_logical_id(
            client_row.file_id, collection_sizes["files"], "file_id", "clients"
        )
        if client_row.scope_id is not None:
            require_logical_id(
                client_row.scope_id, collection_sizes["scopes"], "scope_id", "clients"
            )
    for op_row in parsed_rows.get("ops", ()):
        require_logical_id(op_row.file_id, collection_sizes["files"], "file_id", "ops")
        require_logical_id(
            op_row.scope_id, collection_sizes["scopes"], "scope_id", "ops"
        )
        if op_row.client_id is not None:
            require_logical_id(
                op_row.client_id, collection_sizes["clients"], "client_id", "ops"
            )
        if op_row.key_expr_id is not None:
            require_logical_id(
                op_row.key_expr_id, collection_sizes["key_exprs"], "key_expr_id", "ops"
            )
        if op_row.ttl_source_id is not None:
            require_logical_id(
                op_row.ttl_source_id,
                len(parsed_rows.get("ttl_sources", ())),
                "ttl_source_id",
                "ops",
            )
    for serializer_row in parsed_rows.get("serializers", ()):
        require_logical_id(
            serializer_row.op_id, collection_sizes["ops"], "op_id", "serializers"
        )
    for edge_row in parsed_rows.get("edges", ()):
        # edge source_kind/target_kind values are node kinds; only edges whose
        # endpoint kind maps to an id-addressable collection are validated.
        if edge_row.source_kind not in node_kind_sizes:
            continue
        require_logical_id(
            edge_row.source_id,
            node_kind_sizes.get(edge_row.source_kind, 0),
            "source_id",
            "edges",
        )
        require_logical_id(
            edge_row.target_id,
            node_kind_sizes.get(edge_row.target_kind, 0),
            "target_id",
            "edges",
        )
    for tombstone_row in parsed_rows.get("tombstones", ()):
        require_logical_id(
            tombstone_row.logical_id,
            collection_sizes.get(tombstone_row.entity_kind, 0),
            "logical_id",
            "tombstones",
        )


def require_logical_id(
    logical_id: int, target_size: int, field_name: str, source_block: str
) -> None:
    if not (1 <= logical_id <= target_size):
        raise ValueError(
            f"dangling logical id {logical_id} in {field_name!r} of a "
            f"{source_block!r} row: target collection has {target_size} rows"
        )
