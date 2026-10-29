"""EXP-1: the 100-pattern matching-cost harness (FR-6, FR-7, NFR-1, AC-5, AC-6).

Deterministic, pure-Python matching-cost measurement — no SQL, no
measurement DB (the earlier SQLite materialisation scaffolding was removed
as out of scope; ADR-105 stays measurement-only and never touches the C-5
store, sharing no module with ``redis_intel``). Modules:

- ``patterns``    — the exactly-100 seeded, code-enumerated GLOB key patterns.
- ``graph``       — the deterministic tier-sized key-expression graph
                    (nodes + ``KEY_FLOW``-style adjacency, pure function
                    computed from seed and tier).
- ``matching``    — the FR-7 escalation rungs measured strictly in order
                    (baseline traversal, then closure tables, then
                    materialised projections) plus the nearest-rank
                    p50/p95/max reduction.
- ``harness``     — orchestration, the §4 code-computed verdict, result
                    assembly and the atomic artifact write.
- ``__main__``    — the CLI that writes ``results/exp1.json``.
"""
