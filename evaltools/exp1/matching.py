"""The EXP-1 matching-cost rungs plus the deterministic percentile reduction.

FR-7 escalation ladder, measured strictly in order — the closure table is
**built and measured before** the materialised projections on every run, and
the code enforces that ordering by construction (``run_rungs`` below builds
the closure map before it builds the projection map):

1. ``baseline``                — per pattern: GLOB-match the pattern against the
  whole key-expression universe, then walk ``KEY_FLOW``-style edges depth 3
  from the matched seeds (the recursive-CTE equivalent, pure Python).
2. ``closure_tables``          — per node, the precomputed depth-3 reachable
  set; per pattern: match, then union the seed closures.
3. ``materialised_projections``— per pattern, the precomputed result set; the
  per-iteration cost is a dictionary lookup.

Per-iteration wall-clock timings come from ``time.perf_counter`` and are
reduced to p50/p95/max with the nearest-rank rule (deterministic reduction
over the sorted samples). Timings are the only non-deterministic numbers in
the artifact; the pattern set, graph and result-set sizes are fully
deterministic for a fixed seed.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from fnmatch import fnmatchcase

from evaltools.exp1.graph import TRAVERSAL_DEPTH, TraversalGraph
from evaltools.exp1.patterns import PatternDefinition

P50_PERCENTILE = 50
P95_PERCENTILE = 95

BASELINE_RUNG = "baseline"
CLOSURE_TABLES_RUNG = "closure_tables"
MATERIALISED_PROJECTIONS_RUNG = "materialised_projections"


@dataclass(frozen=True)
class RungMeasurement:
    """One rung's per-iteration timings plus the reduced percentiles (ms)."""

    rung: str
    per_iteration_ms: tuple[float, ...]
    p50_ms: float
    p95_ms: float
    max_ms: float


def nearest_rank_percentile(
    sorted_samples: tuple[float, ...], percentile: int
) -> float:
    """Nearest-rank percentile over already-sorted samples; fails fast when empty."""
    if not sorted_samples:
        raise ValueError("percentile reduction needs at least one sample")
    rank = -(-percentile * len(sorted_samples) // 100)  # ceil division
    return sorted_samples[rank - 1]


def reduce_timings(rung: str, per_iteration_ms: list[float]) -> RungMeasurement:
    """Reduce one rung's per-iteration timings to p50/p95/max (nearest rank)."""
    ordered = tuple(sorted(per_iteration_ms))
    return RungMeasurement(
        rung=rung,
        per_iteration_ms=ordered,
        p50_ms=nearest_rank_percentile(ordered, P50_PERCENTILE),
        p95_ms=nearest_rank_percentile(ordered, P95_PERCENTILE),
        max_ms=ordered[-1],
    )


def run_rungs(
    graph: TraversalGraph, patterns: tuple[PatternDefinition, ...]
) -> tuple[RungMeasurement, RungMeasurement, RungMeasurement]:
    """Measure all three rungs strictly in escalation order.

    The closure table is built and measured before the materialised
    projections — FR-7 ordering, enforced here by construction. The graph
    engine rung is deliberately absent: a specialised graph engine is
    forbidden without user approval (Contract 2 §3.6).
    """
    baseline = _measure_rung(BASELINE_RUNG, patterns, _baseline_iteration(graph))
    depth3_closure = _build_depth3_closure(graph)
    closure_tables = _measure_rung(
        CLOSURE_TABLES_RUNG,
        patterns,
        _closure_iteration(graph.key_expressions, depth3_closure),
    )
    projections = _build_pattern_projections(graph, depth3_closure, patterns)
    materialised_projections = _measure_rung(
        MATERIALISED_PROJECTIONS_RUNG,
        patterns,
        _projection_iteration(projections),
    )
    return baseline, closure_tables, materialised_projections


def _measure_rung(
    rung: str,
    patterns: tuple[PatternDefinition, ...],
    iteration: Callable[[PatternDefinition], object],
) -> RungMeasurement:
    """Time one iteration per pattern, then reduce to p50/p95/max."""
    per_iteration_ms = []
    for pattern in patterns:
        started = time.perf_counter()
        iteration(pattern)
        elapsed_ms = (time.perf_counter() - started) * 1_000.0
        per_iteration_ms.append(elapsed_ms)
    return reduce_timings(rung, per_iteration_ms)


def _baseline_iteration(
    graph: TraversalGraph,
) -> Callable[[PatternDefinition], object]:
    """Per pattern: full-universe GLOB match plus a depth-3 edge walk."""

    def baseline_iteration(pattern: PatternDefinition) -> object:
        matched_seeds = _matched_seeds(graph.key_expressions, pattern)
        return _walk_depth3(graph.adjacency, matched_seeds)

    return baseline_iteration


def _closure_iteration(
    key_expressions: tuple[str, ...],
    depth3_closure: tuple[frozenset[int], ...],
) -> Callable[[PatternDefinition], object]:
    """Per pattern: seed matching (identical work to the baseline, keeping the
    comparison fair) plus the closure-union read."""

    def closure_iteration(pattern: PatternDefinition) -> object:
        matched_seeds = _matched_seeds(key_expressions, pattern)
        matched_result: set[int] = set()
        for seed in matched_seeds:
            matched_result.update(depth3_closure[seed])
        return matched_result

    return closure_iteration


def _projection_iteration(
    projections: dict[str, frozenset[int]],
) -> Callable[[PatternDefinition], object]:
    """Per pattern: one precomputed-result lookup — the materialised read cost."""

    def projection_iteration(pattern: PatternDefinition) -> object:
        return projections[pattern.pattern_id]

    return projection_iteration


def _build_depth3_closure(graph: TraversalGraph) -> tuple[frozenset[int], ...]:
    """Per node, the set reachable within TRAVERSAL_DEPTH hops (cycle-guarded BFS)."""

    def closure_for_node(start: int) -> frozenset[int]:
        reachable: set[int] = {start}
        frontier: set[int] = {start}
        for _ in range(TRAVERSAL_DEPTH):
            next_frontier = {
                neighbour
                for node in frontier
                for neighbour in graph.adjacency[node]
                if neighbour not in reachable
            }
            reachable.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break
        return frozenset(reachable)

    return tuple(closure_for_node(node) for node in range(len(graph.key_expressions)))


def _build_pattern_projections(
    graph: TraversalGraph,
    depth3_closure: tuple[frozenset[int], ...],
    patterns: tuple[PatternDefinition, ...],
) -> dict[str, frozenset[int]]:
    """Per pattern, the precomputed depth-3 result set (the materialised projection)."""
    projections: dict[str, frozenset[int]] = {}
    for pattern in patterns:
        projected_result: set[int] = set()
        for seed in _matched_seeds(graph.key_expressions, pattern):
            projected_result.update(depth3_closure[seed])
        projections[pattern.pattern_id] = frozenset(projected_result)
    return projections


def _matched_seeds(
    key_expressions: tuple[str, ...], pattern: PatternDefinition
) -> tuple[int, ...]:
    return tuple(
        node
        for node, key_expression in enumerate(key_expressions)
        if fnmatchcase(key_expression, pattern.key_pattern)
    )


def _walk_depth3(
    adjacency: tuple[tuple[int, ...], ...], seeds: tuple[int, ...]
) -> set[int]:
    """Depth-3 edge walk from the seeds with a visited-set cycle guard."""
    visited: set[int] = set(seeds)
    current = list(seeds)
    for _ in range(TRAVERSAL_DEPTH):
        next_frontier = [
            neighbour
            for node in current
            for neighbour in adjacency[node]
            if neighbour not in visited
        ]
        visited.update(next_frontier)
        current = next_frontier
        if not current:
            break
    return visited
