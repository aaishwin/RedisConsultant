"""AC-19: each Contract 1 §3.4 rev-3 rule resolves; negatives never callsites."""

import pytest
from conftest import count_silent_drops, ingest_sources
from qa_support import RESOLUTION_RULE_FIXTURES

from redis_intel.frontend import LanguageFrontend, ParseResult
from redis_intel.ir.models import Client


@pytest.fixture(scope="module")
def frontend() -> LanguageFrontend:
    return LanguageFrontend()


def _op_resolutions(
    frontend: LanguageFrontend, path: str
) -> list[tuple[str, str | None]]:
    _parse_results, delta = ingest_sources(
        frontend, {path: RESOLUTION_RULE_FIXTURES[path]}
    )
    return [
        (operation.method, operation.evidence_json.get("resolution"))
        for operation in delta.ops
    ]


def _client_rows(
    frontend: LanguageFrontend, path: str
) -> tuple[list[ParseResult], tuple[Client, ...]]:
    parse_results, _delta = ingest_sources(
        frontend, {path: RESOLUTION_RULE_FIXTURES[path]}
    )
    return parse_results, _delta.clients


def test_r1_same_class_member_binding_resolves(frontend: LanguageFrontend) -> None:
    parse_results, clients = _client_rows(frontend, "r1_field.ts")
    callsites = [
        callsite
        for callsite in parse_results[0].redis_callsites
        if callsite.method == "get"
    ]
    assert [callsite.receiver_text for callsite in callsites] == ["this.client"]
    class_field_rows = [
        client
        for client in clients
        if client.evidence_json.get("resolution") == "class_field_initializer"
    ]
    assert class_field_rows, "R1 field-initializer receiver did not resolve"
    for client in class_field_rows:
        assert client.wrapper_depth == 0
        assert client.evidence_json["DEPTH"] == 0
        assert client.epistemic in ("DETERMINISTIC_FACT", "STATIC_INFERENCE")


def test_r2_constructor_injection_resolves(frontend: LanguageFrontend) -> None:
    _parse_results, clients = _client_rows(frontend, "r2_injection.ts")
    injected_rows = [
        client
        for client in clients
        if client.evidence_json.get("resolution") == "constructor_injection"
    ]
    assert injected_rows, "R2 constructor-injection receiver did not resolve"
    for client in injected_rows:
        # DEPTH 1: one inferential hop through the type annotation; the concrete
        # construction lives outside the file, so the row is STATIC_INFERENCE
        # with the annotation name as construction.
        assert client.wrapper_depth == 1
        assert client.evidence_json["DEPTH"] == 1
        assert client.epistemic == "STATIC_INFERENCE"
        assert client.construction == "Redis"
    resolutions = _op_resolutions(frontend, "r2_injection.ts")
    assert ("get", "constructor_injection") in resolutions


def test_r3_same_file_factory_return_resolves(frontend: LanguageFrontend) -> None:
    _parse_results, clients = _client_rows(frontend, "r3_factory.ts")
    factory_rows = [
        client
        for client in clients
        if client.evidence_json.get("resolution") == "factory_return"
    ]
    assert factory_rows, "R3 factory-return receiver did not resolve"
    for client in factory_rows:
        # DEPTH 1: the factory body is a direct construction.
        assert client.wrapper_depth == 1
        assert client.evidence_json["DEPTH"] == 1
    resolutions = _op_resolutions(frontend, "r3_factory.ts")
    assert ("get", "factory_return") in resolutions


def test_r3_factory_wrapping_r2_injection_reaches_depth_two(
    frontend: LanguageFrontend,
) -> None:
    """R3 = 1 + inner form's DEPTH: factory over an R2 injection is DEPTH 2."""
    from qa_support import PHASE1_FIXTURE_SOURCES

    parse_results = [
        frontend.parse(
            "two_layer_chain.ts", PHASE1_FIXTURE_SOURCES["two_layer_chain.ts"].encode()
        )
    ]
    from redis_intel.ir import IrBuilder

    delta = IrBuilder.ingest(parse_results)
    clients = delta.clients
    assert parse_results, "two-layer chain fixture must parse"
    depth_two_rows = [
        client for client in clients if client.evidence_json.get("DEPTH") == 2
    ]
    assert depth_two_rows, "no client row observed the DEPTH-2 chain"
    for client in depth_two_rows:
        assert client.wrapper_depth == 2
        assert client.epistemic == "STATIC_INFERENCE"


def test_r3_factory_bound_local_resolves(frontend: LanguageFrontend) -> None:
    parse_results, _clients = _client_rows(frontend, "r3_factory_local.ts")
    local_callsites = [
        callsite
        for callsite in parse_results[0].redis_callsites
        if callsite.receiver_text == "boundClient"
    ]
    assert local_callsites, "a local bound to a same-file factory return must resolve"


def test_r4_dynamic_require_resolves_in_both_forms(frontend: LanguageFrontend) -> None:
    # Form 1: new (require("ioredis"))(...) — the require result is the class.
    parse_results_direct, clients_direct = _client_rows(
        frontend, "r4_require_direct.ts"
    )
    direct_rows = [
        client
        for client in clients_direct
        if client.evidence_json.get("resolution") == "dynamic_require"
    ]
    assert direct_rows, "R4 direct require construction did not resolve"
    for client in direct_rows:
        assert client.wrapper_depth == 0
        assert client.evidence_json["DEPTH"] == 0
        assert client.client_library == "ioredis"
    assert any(
        callsite.receiver_text == "requiredClient"
        for callsite in parse_results_direct[0].redis_callsites
    )
    # Form 2: const Redis = require("ioredis"); new Redis(...) — aliased.
    parse_results_alias, clients_alias = _client_rows(frontend, "r4_require_alias.ts")
    resolved_alias_rows = [
        client
        for client in clients_alias
        if client.client_library == "ioredis"
        and client.epistemic in ("DETERMINISTIC_FACT", "STATIC_INFERENCE")
    ]
    assert resolved_alias_rows, "R4 aliased require construction did not resolve"
    assert any(
        callsite.receiver_text == "constructedClient"
        for callsite in parse_results_alias[0].redis_callsites
    )


def test_r5_unresolvable_receiver_is_never_a_callsite(
    frontend: LanguageFrontend,
) -> None:
    """R5 negative: no callsite, one recorded unresolved entry, zero drops."""
    parse_results, _delta = ingest_sources(
        frontend, {"r5_negative.ts": RESOLUTION_RULE_FIXTURES["r5_negative.ts"]}
    )
    assert not parse_results[0].redis_callsites, (
        "an unresolvable receiver produced a callsite — the R5 negative is broken"
    )
    unresolvable = [
        entry
        for entry in parse_results[0].unresolved
        if entry.reason == "unresolvable_expression"
    ]
    assert len(unresolvable) == 1
    assert "labelsByKey.get" in unresolvable[0].detail


def test_resolution_rule_set_drop_count_is_zero(frontend: LanguageFrontend) -> None:
    parse_results, delta = ingest_sources(frontend, RESOLUTION_RULE_FIXTURES)
    drops = count_silent_drops(parse_results, delta)
    assert drops == [], f"silent drops across the R1–R5 fixture set: {drops}"
