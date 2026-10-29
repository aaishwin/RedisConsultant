"""AC-17 (FR-21): every claim-bearing IR row carries a six-tier epistemic value."""

import pytest
from conftest import ingest_sources  # tests dir is on sys.path
from qa_support import EPISTEMIC_TIERS, PHASE1_FIXTURE_SOURCES

from redis_intel.frontend import LanguageFrontend
from redis_intel.ir import deserialize, serialize


@pytest.fixture(scope="module")
def frontend() -> LanguageFrontend:
    return LanguageFrontend()


def test_every_claim_bearing_row_has_a_six_tier_epistemic_value(
    frontend: LanguageFrontend,
) -> None:
    ingestable_sources = {
        path: source
        for path, source in PHASE1_FIXTURE_SOURCES.items()
        if path != "unsupported_syntax.py"
    }
    parse_results, delta = ingest_sources(frontend, ingestable_sources)
    assert parse_results, "the fixture corpus must ingest"
    claim_bearing_rows: list[tuple[str, object]] = []
    claim_bearing_rows.extend(("scopes", row) for row in delta.scopes)
    claim_bearing_rows.extend(("symbols", row) for row in delta.symbols)
    claim_bearing_rows.extend(("clients", row) for row in delta.clients)
    claim_bearing_rows.extend(("ops", row) for row in delta.ops)
    claim_bearing_rows.extend(("key_exprs", row) for row in delta.key_exprs)
    claim_bearing_rows.extend(("namespaces", row) for row in delta.namespaces)
    claim_bearing_rows.extend(("serializers", row) for row in delta.serializers)
    claim_bearing_rows.extend(("ttl_sources", row) for row in delta.ttl_sources)
    claim_bearing_rows.extend(("edges", row) for row in delta.edges)
    assert claim_bearing_rows, "no claim-bearing rows were emitted at all"
    violations: list[str] = []
    for collection_name, row in claim_bearing_rows:
        epistemic_value = getattr(row, "epistemic", None)
        if epistemic_value is None:
            violations.append(
                f"{collection_name}: epistemic is missing (NOT NULL violated)"
            )
        elif epistemic_value not in EPISTEMIC_TIERS:
            violations.append(

                    f"{collection_name}: epistemic {epistemic_value!r} outside the"
                    f" six-tier enum"

            )
    assert violations == [], f"epistemic violations: {violations}"


def test_epistemic_tiers_survive_the_round_trip(frontend: LanguageFrontend) -> None:
    ingestable_sources = {
        path: source
        for path, source in PHASE1_FIXTURE_SOURCES.items()
        if path != "unsupported_syntax.py"
    }
    _parse_results, delta = ingest_sources(frontend, ingestable_sources)
    deserialized = deserialize(serialize(delta))
    for row in deserialized.ops:
        assert row.epistemic in EPISTEMIC_TIERS
    for row in deserialized.clients:
        assert row.epistemic in EPISTEMIC_TIERS
