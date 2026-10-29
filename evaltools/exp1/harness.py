"""EXP-1 orchestration: run the rungs, compute the §4 verdict, write the artifact.

The verdict is always computed in code from the baseline ``p95_wall_ms`` gate
(p95 ≤ 2000 ms) combined with the ``measurement_environment.label`` — an
advisory run is never reported as a reference-profile pass, and a failing
p95 is never inverted into a pass. The escalation-rung measurements are
ordered evidence only (closure tables built and measured before materialised
projections); they never flip the verdict.

The corpus identity cites the tier-L ``typescript_node`` tree sha256 recorded
in ``results/determinism.json`` (the canonical EXP-1 envelope per PLAN §6.4);
the local measurement corpus is generated fresh for every run into
``--corpus-root`` (a throwaway /tmp tree, never committed).
"""

import json
from dataclasses import dataclass
from pathlib import Path

from evaltools.corpus.generator import generate_corpus
from evaltools.corpus.model import LANGUAGES
from evaltools.envreport import build_measurement_environment
from evaltools.exp1.graph import build_traversal_graph
from evaltools.exp1.matching import run_rungs
from evaltools.exp1.patterns import PATTERN_COUNT, build_patterns
from evaltools.gate_evidence import (
    SCHEMA_VERSION,
    require_known_enum,
    write_result_json,
)

P95_GATE_MS = 2000.0
DETERMINISM_RESULT_PATH = Path("results/determinism.json")

REFERENCE_VERDICTS = ("PASS", "FAIL")
ADVISORY_VERDICTS = ("advisory-pass", "advisory-fail")
LABEL_REFERENCE = "reference"
LABEL_ADVISORY = "advisory"

ESCALATION_RUNG_OUTCOMES = ("failed", "adopted")


@dataclass(frozen=True)
class RungEvidence:
    """One measured escalation rung, in FR-7 ladder order."""

    rung: str
    measured_p95_ms: float
    outcome: str


@dataclass(frozen=True)
class ExperimentSummary:
    """Typed view of one EXP-1 run for the CLI; the payload dict feeds the artifact."""

    pattern_count: int
    edge_count: int
    baseline_p50_ms: float
    baseline_p95_ms: float
    baseline_max_ms: float
    escalation_rungs: tuple[RungEvidence, ...]
    measurement_label: str
    verdict: str
    result_path: Path


def compute_verdict(p95_wall_ms: float, environment_label: str) -> str:
    """Compute the §4 verdict from the gate and the environment label — in code."""
    gate_pass = p95_wall_ms <= P95_GATE_MS
    if environment_label == LABEL_REFERENCE:
        return "PASS" if gate_pass else "FAIL"
    if environment_label == LABEL_ADVISORY:
        return "advisory-pass" if gate_pass else "advisory-fail"
    raise ValueError(
        f"results/exp1.json: unknown measurement_environment label "
        f"{environment_label!r}; expected {LABEL_REFERENCE!r} or {LABEL_ADVISORY!r}"
    )


def load_reference_corpus_tree_sha256(
    determinism_result_path: Path = DETERMINISM_RESULT_PATH,
) -> str:
    """Cite the tier-L typescript_node tree sha256 from results/determinism.json."""
    try:
        determinism_payload = json.loads(
            determinism_result_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(

                f"cannot read the determinism evidence at {determinism_result_path}:"
                f" {error}"

        ) from error
    if (
        determinism_payload.get("tier") != "L"
        or determinism_payload.get("language") != "typescript_node"
    ):
        raise ValueError(
            f"{determinism_result_path}: expected the tier-L typescript_node "
            f"determinism evidence, found tier={determinism_payload.get('tier')!r} "
            f"language={determinism_payload.get('language')!r}"
        )
    tree_sha256 = determinism_payload.get("run_a_tree_sha256")
    if not isinstance(tree_sha256, str) or len(tree_sha256) != 64:
        raise ValueError(

                f"{determinism_result_path}: run_a_tree_sha256 is missing or not 64"
                f" hex chars"

        )
    return tree_sha256


def _escalation_rung_evidence(
    closure_tables_ms: float, materialised_projections_ms: float
) -> tuple[RungEvidence, ...]:
    """Ordered FR-7 evidence: closure tables first, then materialised projections."""

    def rung_evidence(rung: str, measured_p95_ms: float) -> RungEvidence:
        outcome = "adopted" if measured_p95_ms <= P95_GATE_MS else "failed"
        return RungEvidence(rung=rung, measured_p95_ms=measured_p95_ms, outcome=outcome)

    return (
        rung_evidence("closure_tables", closure_tables_ms),
        rung_evidence("materialised_projections", materialised_projections_ms),
    )


def run_experiment(
    seed: int,
    tier: str,
    language: str,
    result_path: Path,
    corpus_root: Path,
) -> ExperimentSummary:
    """Run EXP-1 end to end and atomically write ``results/exp1.json``."""
    require_known_enum(tier, ("S", "M", "L"), "results/exp1.json", "tier")
    require_known_enum(language, LANGUAGES, "results/exp1.json", "language")

    # Throwaway measurement corpus — validates the tier/language pair and stays
    # in /tmp (generated corpora are never committed).
    generate_corpus(seed, tier, language, corpus_root)

    patterns = build_patterns(seed)
    if len(patterns) != PATTERN_COUNT:
        raise RuntimeError(

                f"pattern set built {len(patterns)} entries, expected exactly"
                f" {PATTERN_COUNT}"

        )
    graph = build_traversal_graph(seed, tier)
    baseline, closure_tables, materialised_projections = run_rungs(graph, patterns)

    measurement_environment = build_measurement_environment()
    environment_label = str(measurement_environment["label"])
    p95_wall_ms = baseline.p95_ms
    verdict = compute_verdict(p95_wall_ms, environment_label)
    escalation_rungs = _escalation_rung_evidence(
        closure_tables.p95_ms, materialised_projections.p95_ms
    )

    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "tier": tier,
        "language": language,
        "checksum_manifest_tree_sha256": load_reference_corpus_tree_sha256(),
        "edge_count": graph.edge_count,
        "pattern_count": len(patterns),
        "p95_wall_ms": p95_wall_ms,
        # Fixed choice recorded here: a percentile summary block over the 100
        # per-iteration baseline timings (nearest-rank reduction), per §3.6.
        "per_pattern_ms": {
            "basis": (
                "nearest-rank percentiles over the 100 per-pattern baseline iterations"
            ),
            "p50_ms": baseline.p50_ms,
            "p95_ms": baseline.p95_ms,
            "max_ms": baseline.max_ms,
        },
        "measurement_environment": measurement_environment,
        "verdict": verdict,
        "escalation_rungs": [
            {
                "rung": rung_evidence.rung,
                "measured_p95_ms": rung_evidence.measured_p95_ms,
                "outcome": rung_evidence.outcome,
            }
            for rung_evidence in escalation_rungs
        ],
    }
    require_known_enum(
        verdict, REFERENCE_VERDICTS + ADVISORY_VERDICTS, "results/exp1.json", "verdict"
    )
    for rung_evidence in escalation_rungs:
        require_known_enum(
            rung_evidence.rung,
            ("closure_tables", "materialised_projections"),
            "results/exp1.json",
            "escalation_rungs.rung",
        )
        require_known_enum(
            rung_evidence.outcome,
            ESCALATION_RUNG_OUTCOMES,
            "results/exp1.json",
            "escalation_rungs.outcome",
        )
    write_result_json(result_path, payload)
    return ExperimentSummary(
        pattern_count=len(patterns),
        edge_count=graph.edge_count,
        baseline_p50_ms=baseline.p50_ms,
        baseline_p95_ms=baseline.p95_ms,
        baseline_max_ms=baseline.max_ms,
        escalation_rungs=escalation_rungs,
        measurement_label=environment_label,
        verdict=verdict,
        result_path=result_path,
    )
