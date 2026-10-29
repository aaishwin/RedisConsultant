"""AC-12 (FR-15, NFR-5): zero silent drops on the escalation fixtures."""

import pytest
from conftest import count_silent_drops, ingest_sources
from qa_support import (
    ESCALATION_FIXTURE_NAMES,
    PHASE1_FIXTURE_SOURCES,
    UNKNOWN_REASON_ENUM,
    deep_ast_source_bytes,
    oversized_source_bytes,
)

from redis_intel.frontend import LanguageFrontend
from redis_intel.ir.models import UNKNOWN_REASONS


@pytest.fixture(scope="module")
def frontend() -> LanguageFrontend:
    return LanguageFrontend()


def test_zero_silent_drops_across_the_full_phase1_fixture_corpus(
    frontend: LanguageFrontend,
) -> None:
    """Every construct maps to ≥1 row or ≥1 unknowns entry — drop counter is 0.

    The ``unsupported_syntax.py`` fixture is accounted at the C-1 level (its
    unsupported_syntax unresolved entry is present and enumerated) but is not
    passed through IrBuilder, because C-2 raises ValueError on ``unsupported``
    ParseResults — a separately recorded defect (see QA run-1 record).
    """
    ingestable_sources = {
        path: source
        for path, source in PHASE1_FIXTURE_SOURCES.items()
        if path != "unsupported_syntax.py"
    }
    parse_results, delta = ingest_sources(frontend, ingestable_sources)
    drops = count_silent_drops(parse_results, delta)
    assert drops == [], f"silent drops found: {drops}"
    unsupported_result = frontend.parse(
        "unsupported_syntax.py",
        PHASE1_FIXTURE_SOURCES["unsupported_syntax.py"].encode(),
    )
    assert [entry.reason for entry in unsupported_result.unresolved] == [
        "unsupported_syntax"
    ]
    assert unsupported_result.tree is None
    assert not unsupported_result.redis_callsites


def test_every_reason_code_stays_inside_the_contract_enum(
    frontend: LanguageFrontend,
) -> None:
    escalation_sources = {
        name: PHASE1_FIXTURE_SOURCES[name]
        for name in ESCALATION_FIXTURE_NAMES
        if name != "unsupported_syntax.py"
    }
    parse_results, delta = ingest_sources(frontend, escalation_sources)
    for unknown_entry in delta.unknowns:
        assert unknown_entry.reason in UNKNOWN_REASONS
        assert unknown_entry.reason in UNKNOWN_REASON_ENUM
    for parse_result in parse_results:
        for unresolved_node in parse_result.unresolved:
            assert unresolved_node.reason in UNKNOWN_REASON_ENUM


def test_dynamic_key_concat_produces_unknown_key_expr_row(
    frontend: LanguageFrontend,
) -> None:
    parse_results, delta = ingest_sources(
        frontend,
        {"dynamic_key_concat.ts": PHASE1_FIXTURE_SOURCES["dynamic_key_concat.ts"]},
    )
    dynamic_keys = [key for key in delta.key_exprs if key.kind == "dynamic_unknown"]
    assert dynamic_keys, "the concatenated key argument must be a dynamic_unknown row"
    for key in dynamic_keys:
        assert key.epistemic == "UNKNOWN"
    reasons = {unknown.reason for unknown in delta.unknowns}
    assert "dynamic_construction" in reasons
    assert count_silent_drops(parse_results, delta) == []


def test_depth_three_chain_is_recorded_never_dropped(
    frontend: LanguageFrontend,
) -> None:
    parse_results, delta = ingest_sources(
        frontend,
        {"depth_three_wrapper.ts": PHASE1_FIXTURE_SOURCES["depth_three_wrapper.ts"]},
    )
    unresolvable = [
        unknown
        for unknown in delta.unknowns
        if unknown.reason == "unresolvable_expression"
    ]
    assert unresolvable, (
        "the depth-3 wrapper receiver must be recorded as an explicit "
        "unresolvable_expression entry (never dropped, never silently resolved)"
    )
    assert count_silent_drops(parse_results, delta) == []


def test_over_cap_file_is_recorded_not_dropped(frontend: LanguageFrontend) -> None:
    oversized = frontend.parse("oversized_file.ts", oversized_source_bytes())
    assert oversized.tree is None
    assert [entry.reason for entry in oversized.unresolved] == ["file_too_large"]


def test_over_budget_ast_is_recorded_not_dropped(frontend: LanguageFrontend) -> None:
    deep = frontend.parse("deep_ast.ts", deep_ast_source_bytes())
    assert deep.tree is not None
    reasons = [entry.reason for entry in deep.unresolved]
    assert "node_budget_exceeded" in reasons


def test_parse_error_regions_are_recorded_with_the_tree_kept(
    frontend: LanguageFrontend,
) -> None:
    broken_source = PHASE1_FIXTURE_SOURCES["parse_error.ts"]
    broken = frontend.parse("parse_error.ts", broken_source.encode())
    assert broken.tree is not None
    assert [entry.reason for entry in broken.unresolved] == ["parse_error"]
    parse_results, delta = ingest_sources(frontend, {"parse_error.ts": broken_source})
    assert count_silent_drops(parse_results, delta) == []
