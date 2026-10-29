# Phase-1 Gate Report — IR Extraction (C-1 ingestion, C-2 IR builder, C-7 skeleton)

Task: rd-20261026-194406-6123 (requirements revision 2, approved plan revision 2) · Role: qa · Dispatch d-4823fb
Scope of this report: Phase 1 only — C-1 language frontend (FR-13..FR-15), C-2 IR extraction (FR-16..FR-19), the minimal C-7 redaction skeleton (FR-20) and epistemic tiers (FR-21). Acceptance criteria AC-11..AC-20 (plus AC-18, the rev-2 parser-pin criterion) per `requirements.md` and `contracts/ir-boundary.md` rev 3.

## Verdict

**Overall Phase-1 verdict: NOT PASSED.** The gate fails on **AC-7 / NFR-2, which is UNMET**. Phase 1 **works for statically-declarable client forms and does not work for bullmq's forms**: bullmq v6.4.2 binds clients as `await this.connection.client`, via adapter generics (`TClient extends Redis | Cluster`), via `(client as any)` casts, and via cross-file factories — forms that Contract 1 rev 3 resolution rules R1–R4 do not cover, so the EXP-2 prototype measured zero true-positive key templates (precision 0.0, undefined at TP+FP = 0; recall 0.0, 0/38; `results/exp2.json`). The user decided to ship with EXP-2 undemonstrated rather than build type-aware resolution. **AC-10 is met by these two reports.** All other Phase-1 criteria are met or explicitly annotated below.

## Acceptance-criteria table (Phase 1)

| AC | Requirement | Status | Evidence (artifact path / test id) |
|---|---|---|---|
| AC-1 | FR-1, FR-2 — generator emits TS/Node + Python synthetic repos with injection manifests | met | `evaltools/corpus/injection-manifest.json` (10,000 files: 6,000 filler / 2,700 pattern_rich / 300 escalation / 1,000 defect); `tests/phase0/test_injection_manifest.py` |
| AC-2 | FR-3, NFR-3 — byte-identical double-run at same seed | met | `results/determinism.json`: PASS; run_a == run_b == `860e55f7c1536e50fa40fc71367377785fbd08ea2b75771334e037ee8f29c1ea`, seed 194406, tier L; `tests/phase0/test_determinism.py` |
| AC-3 | FR-4 — tier-L mix 60/30/10, ≥ 25 planted defects per MVP rule, ≥ 10 escalation entries | met | `evaltools/corpus/injection-manifest.json`: mix 6,000/3,000/1,000 = 60/30/10; 250 defects/rule (INV-002, TTL-001, NS-003, RACE-004); 300 escalation entries |
| AC-4 | FR-5 — scripted 20-commit series, seven change kinds | met | `evaltools/corpus/commit-series.json`: 20 commits, all 7 change kinds; `tests/phase0/test_commit_series.py` |
| AC-5 | FR-6, NFR-1 — EXP-1 depth-3 traversal p95 recorded with env block | met (advisory) | `results/exp1.json`: 100 patterns, 2,000 edges, p50/p95/max ≈ 0.179/0.193/0.233 ms, verdict `advisory-pass`, `measurement_environment.label` `advisory`, `ram_gb` 8, `is_reference_profile` false; `tests/phase0/test_exp1_result.py` |
| AC-6 | FR-7 — escalation rungs measured in order; no unapproved graph engine | met | `results/exp1.json`: closure tables measured before materialised projections; no graph-engine dependency (D-6) |
| AC-7 | FR-8, NFR-2 — EXP-2 prototype precision on labeled bullmq callsites | **UNMET** | `results/exp2.json`: 52 frozen labels (sha256 `82d3307f…`), `c1_only` precision 0.0 (undefined, TP+FP = 0), recall 0.0 (0/38), verdict `fail`. Phase 1 works for statically-declarable clients; bullmq v6.4.2's `await this.connection.client`, `TClient extends Redis | Cluster` generics, `(client as any)` casts and cross-file factories are outside Contract 1 rev 3 rules R1–R4. User decision: ship with EXP-2 undemonstrated rather than build type-aware resolution. |
| AC-8 | FR-9, FR-10 — offline `blocked-pending-corpus` path | not exercised | Branch never fired: pinned bullmq v6.4.2 @ `f42514c3d716dc81c2bbc65b883c9dc545fcb56d` (MIT) fetched successfully (`results/corpus-manifest.json`, verdict pass, `vendored_tree_committed` false); `tests/phase0/test_blocked_corpus.py` covers the offline writer |
| AC-9 | FR-11 — measurement-environment block + advisory/reference labelling | met | `results/exp1.json`: `measurement_environment.label` `advisory`, `ram_gb` 8, `is_reference_profile` false; no `reference` label on any 8 GB measurement |
| AC-10 | FR-12 — committed JSON results + narrative gate reports | met | `results/determinism.json`, `results/exp1.json`, **`results/exp2.json`**, `results/corpus-manifest.json`, `results/phase1-fixtures.json` + **`docs/gates/phase0-gate.md`**, **`docs/gates/phase1-gate.md`** (the two gate reports are the AC-10 evidence for the narrative-report condition; the reports state the NOT PASSED verdict plainly) |
| AC-11 | FR-13, FR-14 — grammar_id matrix; TSX never via the TypeScript grammar | met | `results/phase1-fixtures.json` AC-11 entry; `tests/phase1/test_grammar_matrix.py` (per-extension ParseResult grammar_id/grammar_version; `.tsx` ⇒ `tsx`, structural ERROR divergence proven) |
| AC-12 | FR-15, NFR-5 — zero silent drops; explicit UNKNOWN rows on escalation fixtures | met | `results/phase1-fixtures.json`: `unknown_drop_count` 0; `tests/phase1/test_unknown_drops.py` (unsupported-syntax construct accounted at C-1 and at C-2 as a recorded `unknowns` entry, `subject_kind=file`, `reason=unsupported_syntax`, no files row — fixed in debug attempt 1) |
| AC-13 | FR-16, FR-19 — all 14 entity kinds present; byte-equal round-trip | met | `results/phase1-fixtures.json`: `round_trip_checksum` equal, digest `a0c36a32…`; `tests/phase1/test_serialization_roundtrip.py` (serialize∘deserialize byte-equal + structural equality; INVALIDATES/test-ref kinds exercised at the serialization layer) |
| AC-14 | FR-17 — wrapper DEPTH semantics: depth ≤ 2 concrete, depth ≥ 3 escalates | met | `results/phase1-fixtures.json` AC-14 entry; `tests/phase1/test_wrapper_depth.py` (depth 0/1/2 concrete with DEPTH recorded on client rows and edges; depth-3 ⇒ UNKNOWN + `wrapper_depth_exceeded` + model-hypothesis candidate + DEPTH 3). Reachability note below. |
| AC-15 | FR-18, NFR-2 — C-2 reproduces the recorded EXP-2 measurements as a regression fixture | met | `tests/phase1/test_fr18_exp2_reproduction.py`: the harness-shaped re-run matches the committed `results/exp2.json` per-callsite values (both measurement blocks) exactly; the reproduction itself is faithful — the underlying measurement fails its precision gate (AC-7) |
| AC-16 | FR-20, NFR-4 — sentinel secrets never leak; redaction idempotent | met | `results/phase1-fixtures.json` AC-16 entry; `tests/phase1/test_conn_config_redaction.py::test_sentinel_never_appears_in_any_ir_row_or_artifact`; `sentinel_secret_scan.matches` 0 (`results/phase1-fixtures.json`); construction-call config argument no longer becomes a key expression (debug attempt 1); `redact(redact(x)) == redact(x)` asserted |
| AC-17 | FR-21 — six-tier epistemic on every claim-bearing IR row | met | `results/phase1-fixtures.json` AC-17 entry; `tests/phase1/test_epistemic_tiers.py` (present and six-tier before and after the round trip) |
| AC-18 | FR-13, NFR-3 — exact parser pins, no language pack, no runtime downloads | met | `pyproject.toml` pins `tree-sitter==0.23.2`, `tree-sitter-typescript==0.23.2`, `tree-sitter-javascript==0.23.1`; `tests/phase1/test_parser_pins.py` (no `tree-sitter-language-pack` in pyproject or uv.lock; socket-guarded parse per grammar succeeds) |
| AC-19 | Contract 1 rev 3 §3.4 — each resolution rule resolves; negatives never callsites | met | `results/phase1-fixtures.json` AC-19 entry; `tests/phase1/test_resolution_rules.py` (R1 class_field_initializer DEPTH 0; R2 constructor_injection DEPTH 1 STATIC_INFERENCE; R3 factory_return with factory-over-injection reaching DEPTH 2; R4 dynamic_require both forms; R5 negative never a callsite with one `unresolvable_expression` entry; drop count 0) |
| AC-20 | Contract 1 rev 3 — 14 negative EXP-2 labels stay true negatives | met | `results/phase1 fixtures.json` AC-20 entry; `tests/phase1/test_exp2_negatives.py` (zero false positives in the harness-shaped re-run; zero same-method callsites on every negative span) |

## Contract rev-3 traceability (contracts/ir-boundary.md, rev 3, signed backend_lead)

| Contract rule (§3.4) | Phase-1 realisation | Evidence |
|---|---|---|
| R1 — class field initializer | Resolves at DEPTH 0 | `tests/phase1/test_resolution_rules.py` R1 fixture |
| R2 — constructor injection (annotation construction) | Resolves at DEPTH 1, epistemic STATIC_INFERENCE | same test, R2 fixture |
| R3 — factory return | Resolves at DEPTH 1; factory-over-injection reaches DEPTH 2 concrete | same test, R3 fixture |
| R4 — dynamic require, both forms | Resolves at DEPTH 0 | same test, R4 fixtures |
| R5 — negative: non-construction receiver expressions are never callsites | Negative never a callsite; one recorded `unresolvable_expression` entry; drop count 0 | same test, R5 fixtures; `tests/phase1/test_unknown_drops.py` |
| Contract §3.10 — frozen EXP-2 label set | 52 frozen labels, sha256 `82d3307f…` (`results/exp2.json`) | Deviation note below |
| Contract §3.4 boundary against bullmq forms | **Not covered** for `await this.connection.client`, `TClient extends Redis \| Cluster`, `(client as any)`, cross-file factories — the AC-7 failure mode | `results/exp2.json` |

## The three defects fixed in debug attempt 1 (with regression evidence)

1. **AC-16 — sentinel secret leaked into `key_exprs`.** The construction call's config argument was being emitted as a key expression, so the sentinel secret materialised in the serialized IR. Fixed: the config argument no longer becomes a key expression; every `clients.conn_config` row is redacted through the governance seam, and `redact(redact(x)) == redact(x)` holds. Regression evidence: `tests/phase1/test_conn_config_redaction.py::test_sentinel_never_appears_in_any_ir_row_or_artifact` passed in this run, and `results/phase1-fixtures.json` `sentinel_secret_scan.matches` = 0. The AC-16 regression test now passes unchanged from the pre-fix version.
2. **Natural-key row ordering.** Rows were emitted in nondeterministic order, changing the round-trip digest. Fixed: rows ordered by natural key before serialisation. Regression evidence: `results/phase1-fixtures.json` `round_trip_checksum` equal, digest `a0c36a32…`.
3. **`ValueError` crash on `grammar_id='unsupported'`.** C-2 crashed with a `ValueError` when ingesting a C-1 `ParseResult` whose grammar could not resolve (unsupported syntax). Fixed: the construct is accounted at C-1 level and at C-2 as a recorded `unknowns` entry (`subject_kind=file`, `reason=unsupported_syntax`) with no `files` row (`FileRow.grammar_id` has no `unsupported` member). Regression evidence: `tests/phase1/test_unknown_drops.py` passed in this run with `unknown_drop_count` 0.

## Digest change note

The Phase-1 round-trip digest legitimately changed from `05308d37…` to `a0c36a32…` when natural-key row ordering was fixed (debug attempt 1, defect 2). The digest is a function of row order among other things; the ordering fix is the sole cause of the change, and the round-trip remains byte-equal (`round_trip_checksum` equal). The old digest is superseded; `a0c36a32…` is the committed value in `results/phase1-fixtures.json`.

## Label-count deviation note (no inflation)

§3.10 of the contract text says **50** EXP-2 labels; the committed artifact records the real number, **52** frozen labels (sha256 `82d3307f…`, `results/exp2.json`). This deviation is documented rather than papered over: the artifact's 52 labels are authoritative and the contract text remains unchanged at 50.

## AC-14 reachability note

AC-14's depth-≥3 escalation is verified at the **`ClientChainResolver` level**: `tests/phase1/test_wrapper_depth.py` proves the depth-3 chain produces UNKNOWN + `wrapper_depth_exceeded` + a model-hypothesis candidate with DEPTH 3 recorded. The full end-to-end path never exercises it because the C-1 receiver gate (contract-conformant R5) never emits >1-hop receivers, so a depth-3 chain cannot arrive through the public pipeline in Phase 1. The resolver-level proof satisfies AC-14's requirement that depth ≥ 3 escalates and never silently drops; the pipeline-level path is untested by construction.

## Overall verdict

**NOT PASSED.** Phase 1 works for statically-declarable clients and does not work for bullmq's forms (AC-7/NFR-2 unmet — precision 0.0, recall 0.0, `results/exp2.json`). The user decided to ship with EXP-2 undemonstrated rather than build type-aware resolution. AC-10 is met by these two reports (`docs/gates/phase0-gate.md`, `docs/gates/phase1-gate.md`). Every other criterion is met or its non-execution is explicitly annotated; no skipped, inconclusive or non-executed check is counted as a pass.
