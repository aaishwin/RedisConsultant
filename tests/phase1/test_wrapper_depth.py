"""AC-14 (FR-17): wrapper DEPTH semantics — concrete ≤2, depth-3 escalates."""

from conftest import ingest_sources  # tests dir is on sys.path
from qa_support import PHASE1_FIXTURE_SOURCES

from redis_intel.frontend import LanguageFrontend
from redis_intel.ir import IrDelta
from redis_intel.ir.models import Client
from redis_intel.ir.resolution import ClientChainResolver


def _resolved_client_rows(delta: IrDelta) -> list[Client]:
    return [
        client for client in delta.clients if client.evidence_json.get("resolution")
    ]


def test_direct_construction_resolves_at_depth_zero(frontend: LanguageFrontend) -> None:
    _parse_results, delta = ingest_sources(
        frontend,
        {"direct_construction.ts": PHASE1_FIXTURE_SOURCES["direct_construction.ts"]},
    )
    resolved_rows = _resolved_client_rows(delta)
    assert resolved_rows, "the direct construction receiver must resolve"
    for client in resolved_rows:
        assert client.wrapper_depth == 0
        assert client.evidence_json["DEPTH"] == 0
        assert client.epistemic == "DETERMINISTIC_FACT"
        assert client.construction == "new Redis"
        assert client.evidence_json["resolution"] == "direct_construction"


def test_one_hop_wrapper_resolves_at_depth_one(frontend: LanguageFrontend) -> None:
    _parse_results, delta = ingest_sources(
        frontend, {"one_hop_wrapper.ts": PHASE1_FIXTURE_SOURCES["one_hop_wrapper.ts"]}
    )
    resolved_rows = [
        client for client in delta.clients if client.evidence_json.get("DEPTH") == 1
    ]
    assert resolved_rows, "the one-hop alias wrapper must resolve at DEPTH 1"
    for client in resolved_rows:
        assert client.wrapper_depth == 1
        assert client.epistemic == "STATIC_INFERENCE"


def test_depth_two_chain_resolves_concrete_with_depth_recorded(
    frontend: LanguageFrontend,
) -> None:
    _parse_results, delta = ingest_sources(
        frontend, {"two_layer_chain.ts": PHASE1_FIXTURE_SOURCES["two_layer_chain.ts"]}
    )
    resolved_rows = _resolved_client_rows(delta)
    assert resolved_rows, "the depth-2 chain must resolve to a concrete clients row"
    for client in resolved_rows:
        assert client.wrapper_depth == 2
        assert client.evidence_json["DEPTH"] == 2
        assert client.epistemic == "STATIC_INFERENCE"
        assert "unresolved_reason" not in client.evidence_json
    # Every wrapper-propagation edge carries the DEPTH attribute (§5.2).
    depth_edges = [edge for edge in delta.edges if "DEPTH" in edge.evidence_json]
    assert depth_edges, "no edge records the DEPTH attribute"
    for edge in depth_edges:
        assert isinstance(edge.evidence_json["DEPTH"], int)
        assert edge.evidence_json["DEPTH"] >= 0


def test_depth_three_chain_escalates_with_depth_and_candidate_flag(
    frontend: LanguageFrontend,
) -> None:
    """The depth-3 chain escalates exactly per §5.2 — never silently dropped.

    Reachability note (recorded in qa/run-1.md): the C-1 receiver gate resolves
    only the five §3.4 rules, so a depth-3 wrapper receiver is not a callsite
    (R5); it surfaces as an explicit ``unresolvable_expression`` entry. The
    §5.2 escalation itself is implemented in the C-2 resolver and is verified
    here at that level with the same parsed tree.
    """
    _parse_results, delta = ingest_sources(
        frontend,
        {"depth_three_wrapper.ts": PHASE1_FIXTURE_SOURCES["depth_three_wrapper.ts"]},
    )
    assert any(
        unknown.reason == "unresolvable_expression" for unknown in delta.unknowns
    ), "the depth-3 receiver must be recorded, never dropped"
    resolver = ClientChainResolver(_parse_results[0].tree)
    depth_one = resolver.resolve("firstWrapper")
    depth_two = resolver.resolve("secondWrapper")
    depth_three = resolver.resolve("thirdWrapper")
    assert depth_one is not None and depth_one.wrapper_depth == 1
    assert depth_two is not None and depth_two.wrapper_depth == 2
    assert depth_three is not None
    assert depth_three.wrapper_depth == 3
    assert depth_three.epistemic == "UNKNOWN"
    assert depth_three.evidence_json["unresolved_reason"] == "wrapper_depth_exceeded"
    assert depth_three.evidence_json["model_hypothesis_candidate"] is True
    assert depth_three.evidence_json["DEPTH"] == 3
