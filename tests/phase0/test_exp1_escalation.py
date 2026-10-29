"""AC-6 (FR-7): escalation-rung ordering and the graph-engine prohibition."""

import json
from pathlib import Path

EXP1_RESULT_PATH = Path("results/exp1.json")
ALLOWED_RUNGS = ("closure_tables", "materialised_projections")
ALLOWED_OUTCOMES = ("failed", "adopted")


def test_no_graph_engine_rung_without_user_approval() -> None:
    result = json.loads(EXP1_RESULT_PATH.read_text(encoding="utf-8"))
    for rung in result.get("escalation_rungs", []):
        assert rung["rung"] in ALLOWED_RUNGS, (
            f"rung {rung['rung']!r} is outside the SQLite-internal ladder; a "
            "graph-engine rung requires recorded user approval"
        )
        assert rung["outcome"] in ALLOWED_OUTCOMES
        assert isinstance(rung["measured_p95_ms"], (int, float))


def test_closure_tables_measured_before_materialised_projections() -> None:
    result = json.loads(EXP1_RESULT_PATH.read_text(encoding="utf-8"))
    rungs = result.get("escalation_rungs", [])
    rung_names = [rung["rung"] for rung in rungs]
    if "materialised_projections" in rung_names:
        assert "closure_tables" in rung_names, (
            "materialised projections adopted without a recorded closure-tables "
            "baseline measurement"
        )
        assert rung_names.index("closure_tables") < rung_names.index(
            "materialised_projections"
        ), "closure tables must be measured before materialised projections"


def test_failure_driven_escalation_matches_the_verdict() -> None:
    """When EXP-1 passed, no rung may claim a measured *failure* of its baseline."""
    result = json.loads(EXP1_RESULT_PATH.read_text(encoding="utf-8"))
    if result["verdict"] in ("PASS", "advisory-pass"):
        failed_rungs = [
            rung
            for rung in result.get("escalation_rungs", [])
            if rung["outcome"] == "failed"
        ]
        assert not failed_rungs, (
            "the EXP-1 verdict is a pass, so no escalation rung should record a "
            f"failed baseline measurement, found: {failed_rungs}"
        )
