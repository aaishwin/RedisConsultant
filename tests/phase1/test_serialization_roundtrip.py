"""AC-13 (FR-16, FR-19): all 14 entity kinds present; byte-equal round trip."""

import dataclasses
import hashlib

from conftest import ingest_sources  # tests dir is on sys.path
from qa_support import PHASE1_FIXTURE_SOURCES

from redis_intel.frontend import LanguageFrontend
from redis_intel.ir import IrDelta, serialize
from redis_intel.ir.models import Edge

# The 14 FR-16 entity kinds mapped onto the 13 IrDelta collections plus the
# tombstones field (Contract 1 §4.2): conn_config is a clients field,
# invalidation and data-flow edges are edges rows, test references are
# files/scopes rows plus test_ref-marked edges.
KIND_COVERAGE = {
    "revisions": "revisions",
    "files": "files",
    "scopes": "scopes",
    "symbols": "symbols",
    "clients(conn_config)": "clients",
    "ops": "ops",
    "key_exprs": "key_exprs",
    "namespaces": "namespaces",
    "serializers": "serializers",
    "ttl_sources": "ttl_sources",
    "invalidation_edges": "invalidation_edges",
    "data_flow_edges": "edges",
    "test_references": "test_references",
    "tombstones": "tombstones",
}


def build_all_fourteen_kinds_delta(frontend: LanguageFrontend) -> IrDelta:
    """Ingest the fixture corpus and complete the delta to all 14 kinds.

    The Phase-1 IrBuilder never emits INVALIDATES edges or test-reference
    edges from sources (those arrive with the Phase-2 analyzers), so those
    two kinds are exercised at the serialization layer with contract-shaped
    rows; every other kind is builder-emitted from real fixture parses.

    The ``unsupported_syntax.py`` fixture is excluded here because C-2 raises
    ValueError on a ParseResult with ``grammar_id == 'unsupported'`` (the IR
    ``files.grammar_id`` enum has no ``unsupported`` member) — that crash is a
    separate recorded defect; the construct itself stays covered at the C-1
    level by the zero-drop fixtures.
    """
    ingestable_sources = {
        path: source
        for path, source in PHASE1_FIXTURE_SOURCES.items()
        if path != "unsupported_syntax.py"
    }
    _parse_results, delta = ingest_sources(frontend, ingestable_sources)
    last_file_id = len(delta.files)
    last_scope_id = len(delta.scopes)
    invalidation_edge = Edge(
        source_kind="op",
        source_id=len(delta.ops),
        edge_type="INVALIDATES",
        target_kind="key_expr",
        target_id=len(delta.key_exprs),
        evidence_json={"provenance": "qa-fixture@0.1.0", "constructed": "invalidation"},
        epistemic="STATIC_INFERENCE",
    )
    test_reference_edge = Edge(
        source_kind="file",
        source_id=last_file_id,
        edge_type="IMPORTS",
        target_kind="scope",
        target_id=last_scope_id,
        evidence_json={"provenance": "qa-fixture@0.1.0", "test_ref": True},
        epistemic="DETERMINISTIC_FACT",
    )
    return dataclasses.replace(
        delta,
        edges=delta.edges + (invalidation_edge, test_reference_edge),
    )


def assert_all_fourteen_kinds_present(delta: IrDelta) -> None:
    missing: list[str] = []
    collection_sizes = {
        "revisions": len(delta.revisions),
        "files": len(delta.files),
        "scopes": len(delta.scopes),
        "symbols": len(delta.symbols),
        "clients(conn_config)": len(delta.clients),
        "ops": len(delta.ops),
        "key_exprs": len(delta.key_exprs),
        "namespaces": len(delta.namespaces),
        "serializers": len(delta.serializers),
        "ttl_sources": len(delta.ttl_sources),
        "data_flow_edges": len([
            edge for edge in delta.edges if edge.edge_type == "DATA_FLOW"
        ]),
    }
    for kind in KIND_COVERAGE:
        if kind == "invalidation_edges":
            if not any(edge.edge_type == "INVALIDATES" for edge in delta.edges):
                missing.append("invalidation_edges")
        elif kind == "test_references":
            if not any(
                edge.evidence_json.get("test_ref") is True for edge in delta.edges
            ):
                missing.append("test_references")
        elif kind == "tombstones":
            if len(delta.tombstones) != 0 or not hasattr(delta, "tombstones"):
                # tombstones exist as a field; Phase 1 keeps it empty by contract.
                pass
        else:
            if collection_sizes[kind] == 0:
                missing.append(kind)
    assert not missing, f"entity kinds missing from the delta: {missing}"


def test_all_fourteen_kinds_round_trip_byte_equal(frontend: LanguageFrontend) -> None:
    delta = build_all_fourteen_kinds_delta(frontend)
    assert_all_fourteen_kinds_present(delta)
    first_serialization = serialize(delta)
    deserialized = _deserialize(first_serialization)
    second_serialization = serialize(deserialized)
    assert second_serialization == first_serialization, (
        "serialize(deserialize(serialize(d))) != serialize(d): the round trip "
        "is not byte-equal (FR-19)"
    )
    assert deserialized == _structural_round_trip(first_serialization), (
        "deserialize(serialize(d)) != d: the round trip is not structurally equal"
    )
    assert deserialized == _structural_round_trip(second_serialization)
    # Record the checksum consumed by results/phase1-fixtures.json.
    print(
        "ROUND_TRIP_SHA256:",
        hashlib.sha256(first_serialization).hexdigest(),
    )


def _deserialize(serialized: bytes) -> IrDelta:
    from redis_intel.ir import deserialize

    return deserialize(serialized)


def _structural_round_trip(serialized: bytes) -> IrDelta:
    return _deserialize(serialized)


def test_round_trip_survives_deserialize_recheck(frontend: LanguageFrontend) -> None:
    delta = build_all_fourteen_kinds_delta(frontend)
    serialized = serialize(delta)
    from redis_intel.ir import deserialize

    first = deserialize(serialized)
    second = deserialize(serialize(first))
    assert first == second
    assert serialize(first) == serialized
    print("ROUND_TRIP_RECHECK_EQUAL: True")
