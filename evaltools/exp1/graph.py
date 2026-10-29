"""The deterministic, tier-sized traversal graph for EXP-1 (ADR-105, pure Python).

The measurement graph is a pure function computed from ``seed`` and ``tier``:
a key-expression universe (built from the same namespace/entity vocabulary as
the pattern set, so patterns are never degenerate) plus a fixed out-degree
``KEY_FLOW``-style adjacency. The same seed always yields the same nodes, the
same edge order and the same ``edge_count``; no wall-clock, randomness or
filesystem state is involved.

Tier sizes are deliberately modest here: the advisory 8 GB profile runs tier S
locally; the tier-L envelope (2–5M edges, NFR-3) belongs on the approved
reference profile where the identical code path gets re-measured. Memory stays
bounded because the node and edge counts are fixed constants from the tier
table below, never a function from input size.
"""

from dataclasses import dataclass

from evaltools.corpus.prng import derive_int
from evaltools.exp1.patterns import PATTERN_ENTITIES, PATTERN_NAMESPACES
from evaltools.gate_evidence import require_known_enum

# Fixed node counts per tier — the memory ceiling is a constant from the code,
# not a property measured from some run (bounded-memory rule).
TIER_KEY_COUNTS = {"S": 1_000, "M": 4_000, "L": 16_000}

# Contiguous clusters the edges live inside, so pattern fan-out (and therefore
# traversal cost) genuinely varies per pattern: a narrow prefix touches one
# cluster, the un-namespaced form touches all clusters.
CLUSTER_COUNT = 8

OUT_EDGES_PER_NODE = 2
TRAVERSAL_DEPTH = 3

KEY_ATTRIBUTES = ("summary", "detail", "index", "meta")
KEY_INSTANCE_MODULUS = 97


@dataclass(frozen=True)
class TraversalGraph:
    """The tier-sized key-expression graph: nodes, adjacency, edge count."""

    key_expressions: tuple[str, ...]
    adjacency: tuple[tuple[int, ...], ...]
    edge_count: int


def build_traversal_graph(seed: int, tier: str) -> TraversalGraph:
    """Build the deterministic seed+tier traversal graph; fail fast on bad tier."""
    require_known_enum(tier, tuple(TIER_KEY_COUNTS), "results/exp1.json", "tier")
    key_count = TIER_KEY_COUNTS[tier]
    key_expressions = tuple(_key_expression(seed, index) for index in range(key_count))
    adjacency = tuple(_out_edges(seed, index, key_count) for index in range(key_count))
    edge_count = key_count * OUT_EDGES_PER_NODE
    return TraversalGraph(
        key_expressions=key_expressions, adjacency=adjacency, edge_count=edge_count
    )


def _key_expression(seed: int, index: int) -> str:
    """One deterministic key expression: namespace + entity + instance + attribute."""
    namespace = PATTERN_NAMESPACES[
        derive_int(seed, "exp1/key-namespace", index, len(PATTERN_NAMESPACES))
    ]
    entity = PATTERN_ENTITIES[
        derive_int(seed, "exp1/key-entity", index, len(PATTERN_ENTITIES))
    ]
    instance = derive_int(seed, "exp1/key-instance", index, KEY_INSTANCE_MODULUS)
    attribute = KEY_ATTRIBUTES[
        derive_int(seed, "exp1/key-attribute", index, len(KEY_ATTRIBUTES))
    ]
    return f"{namespace}{entity}:{instance}:{attribute}"


def _out_edges(seed: int, index: int, key_count: int) -> tuple[int, ...]:
    """Two fixed out-edges for ``index``, both inside the containing cluster."""
    cluster_size = key_count // CLUSTER_COUNT
    cluster_start = (index // cluster_size) * cluster_size
    return tuple(
        cluster_start + derive_int(seed, f"exp1/edge-{slot}", index, cluster_size)
        for slot in range(OUT_EDGES_PER_NODE)
    )
