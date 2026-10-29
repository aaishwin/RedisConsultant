"""The exactly-100 EXP-1 key patterns (FR-6, Contract 2 §3.6 pattern_count).

The pattern set is a pure, seed-driven function: a 10x10 matrix of
namespace x entity GLOB patterns is shuffled with a seeded Fisher-Yates pass
(SHA-256-counter PRF from ``evaltools.corpus.prng`` — the same determinism
mechanism as the corpus generator), then ids P-001..P-100 are enumerated in
code over the shuffled order. For a fixed seed the set, the ids and the
pattern-to-id mapping are always identical; ``build_patterns`` fails fast if
the count ever drifts from exactly 100.

The GLOB wildcards are what makes this a *matching-cost* experiment: each
pattern selects a seed set of key expressions by prefix, so fan-out (and
therefore traversal cost) varies per pattern exactly as PLAN §6.4 EXP-1
prescribes ("100 randomized key patterns").
"""

from dataclasses import dataclass

from evaltools.corpus import content
from evaltools.corpus.prng import derive_int
from evaltools.gate_evidence import require_known_enum

PATTERN_COUNT = 100

# The shared entity vocabulary of the synthetic corpus (evaltools.corpus
# content.py) — patterns and derived key templates draw from one list so the
# GLOB seeds are guaranteed to be non-degenerate across the matrix.
PATTERN_ENTITIES = content.ENTITIES

# Ten namespace prefixes; the empty prefix is the un-namespaced form.
PATTERN_NAMESPACES = (
    "",
    "cache:",
    "sess:",
    "queue:",
    "lock:",
    "rate:",
    "index:",
    "audit:",
    "blob:",
    "metrics:",
)


@dataclass(frozen=True)
class PatternDefinition:
    """One measured traversal seed: a stable id plus its GLOB key pattern."""

    pattern_id: str
    key_pattern: str


def build_patterns(seed: int) -> tuple[PatternDefinition, ...]:
    """Build the exactly-100 seeded, id-enumerated pattern set.

    Deterministic: the same ``seed`` always yields the same 100 patterns in
    the same order (Contract 2 §1). Randomised: which matrix entry lands on
    which P-id is the seeded shuffle — this is PLAN's "randomized key
    patterns", reproducible rather than arbitrary.
    """
    matrix = [
        f"{namespace}{entity}:*"
        for namespace in PATTERN_NAMESPACES
        for entity in PATTERN_ENTITIES
    ]
    if len(matrix) != PATTERN_COUNT:
        raise RuntimeError(

                f"pattern matrix built {len(matrix)} entries, expected exactly"
                f" {PATTERN_COUNT}"

        )
    shuffled = _seeded_shuffle(matrix, seed)
    patterns = tuple(
        PatternDefinition(pattern_id=f"P-{ordinal + 1:03d}", key_pattern=key_pattern)
        for ordinal, key_pattern in enumerate(shuffled)
    )
    if len(patterns) != PATTERN_COUNT:
        raise RuntimeError(

                f"pattern set built {len(patterns)} entries, expected exactly"
                f" {PATTERN_COUNT}"

        )
    for ordinal, pattern in enumerate(patterns):
        require_known_enum(
            pattern.pattern_id,
            {f"P-{index + 1:03d}" for index in range(PATTERN_COUNT)},
            "results/exp1.json",
            f"per_pattern_ms[{ordinal}] pattern id",
        )
    return patterns


def _seeded_shuffle(values: list[str], seed: int) -> list[str]:
    """Fisher-Yates shuffle driven by the shared SHA-256-counter PRF."""
    working = list(values)
    for swap_index in range(len(working) - 1, 0, -1):
        draw_index = derive_int(
            seed, "exp1/pattern-shuffle", swap_index, swap_index + 1
        )
        working[swap_index], working[draw_index] = (
            working[draw_index],
            working[swap_index],
        )
    return working
