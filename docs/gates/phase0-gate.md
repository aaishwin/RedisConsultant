# Phase-0 Gate Report — Discovery / Evaluation Foundation

Task: rd-20261026-194406-6123 (requirements revision 2, approved plan revision 2) · Role: qa · Dispatch d-4823fb
Scope of this report: Phase 0 only — corpus generator + injection manifest (FR-1..FR-5), EXP-1 harness (FR-6..FR-7), EXP-2 harness (FR-8..FR-10), measurement-environment labelling (FR-11) and gate evidence (FR-12). Acceptance criteria AC-1..AC-10 per `requirements.md` (coverage table: FR-1→AC-1 … NFR-5→AC-12).

## Verdict

**Phase-0 gate: NOT PASSED.** AC-7 (FR-8, NFR-2 — EXP-2 key-template precision) is **UNMET**: the EXP-2 result records `c1_only` precision 0.0 (undefined — TP+FP = 0) and recall 0.0 (0/38), verdict `fail` (`results/exp2.json`). AC-1..AC-6, AC-9 and AC-10 are met with committed evidence as itemised below; AC-8's offline branch was not exercised because the pinned corpus fetched successfully.

Recorded disposition (user decision, relayed by the leader): ship with EXP-2 undemonstrated rather than build type-aware client resolution; the D3 rule-scope decision remains recorded as constrained to statically-declarable client forms.

## Root cause of the AC-7 failure (stated plainly)

**AC-7 / NFR-2 UNMET.** bullmq v6.4.2 (pinned SHA `f42514c3d716dc81c2bbc65b883c9dc545fcb56d`, MIT, `results/corpus-manifest.json`) binds clients in forms that Contract 1 rev 3 resolution rules R1–R4 (`contracts/ir-boundary.md`, §3.4) do not cover:

1. `await this.connection.client` — the client is the awaited result of a property on a connection object, not a direct constructor/factory call form;
2. adapter generics of the shape `TClient extends Redis | Cluster` — the concrete client type is bound at the adapter's type parameter, unresolvable without type-aware analysis;
3. `(client as any)` casts that erase the type at the receiver;
4. cross-file factories that construct the client in a module distant from the callsite.

The prototype therefore produced zero true-positive template measurements on the labeled callsites (TP+FP = 0 ⇒ precision undefined, recorded as 0.0), failing the ≥ 80 % precision target. The user decided to ship with EXP-2 undemonstrated rather than extend the rules with type-aware resolution.

## Acceptance-criteria table (Phase 0)

| AC | Requirement | Status | Evidence (artifact path / test id) |
|---|---|---|---|
| AC-1 | FR-1, FR-2 — generator emits TS/Node + Python synthetic repos with injection manifests | met | `evaltools/corpus/injection-manifest.json` (10,000 files: 6,000 filler / 2,700 pattern_rich / 300 escalation / 1,000 defect, with per-rule planted-defect spans); `tests/phase0/test_injection_manifest.py` |
| AC-2 | FR-3, NFR-3 — byte-identical double-run at same seed | met | `results/determinism.json`: PASS; run_a == run_b == `860e55f7c1536e50fa40fc71367377785fbd08ea2b75771334e037ee8f29c1ea`, seed 194406, tier L; `tests/phase0/test_determinism.py` |
| AC-3 | FR-4 — tier-L mix 60/30/10 and ≥ 25 planted defects per MVP rule kind, ≥ 10 escalation entries | met | `evaltools/corpus/injection-manifest.json`: mix 6,000/3,000/1,000 = 60/30/10; 250 planted defects per rule (INV-002, TTL-001, NS-003, RACE-004 — each ≥ 25); 300 escalation entries (≥ 10) |
| AC-4 | FR-5 — scripted 20-commit series with all seven change kinds | met | `evaltools/corpus/commit-series.json`: 20 commits covering all 7 change kinds; `tests/phase0/test_commit_series.py` |
| AC-5 | FR-6, NFR-1 — EXP-1 depth-3 traversal p95 recorded with env block | met (advisory) | `results/exp1.json`: 100 patterns, 2,000 edges, p50/p95/max ≈ 0.179/0.193/0.233 ms, verdict `advisory-pass`, `measurement_environment.label` `advisory`, `ram_gb` 8, `is_reference_profile` false; `tests/phase0/test_exp1_result.py`. See advisory-scope note below. |
| AC-6 | FR-7 — escalation rungs measured in order; no unapproved graph engine | met | `results/exp1.json`: escalation rungs recorded with closure tables measured before materialised projections; no graph-engine dependency introduced (out of scope, D-6) |
| AC-7 | FR-8, NFR-2 — EXP-2 prototype records per-callsite depth/template/tier with computed precision | **UNMET** | `results/exp2.json`: frozen labels (52 entries, sha256 `82d3307f…`), `c1_only` precision 0.0 (undefined, TP+FP = 0), recall 0.0 (0/38), verdict `fail`. Root cause above. |
| AC-8 | FR-9, FR-10 — offline `blocked-pending-corpus` path | not exercised | Conditional branch never fired: network was available and the pinned bullmq checkout was fetched successfully (`results/corpus-manifest.json`, verdict pass, bullmq `f42514c3d716dc81c2bbc65b883c9dc545fcb56d` v6.4.2 MIT, `vendored_tree_committed` false); `tests/phase0/test_blocked_corpus.py` covers the offline writer itself |
| AC-9 | FR-11 — measurement-environment block + advisory/reference labelling | met | `results/exp1.json` carries the `measurement_environment` block with label `advisory`, `ram_gb` 8, `is_reference_profile` false; no result file measured on the 8 GB machine carries the `reference` label |
| AC-10 | FR-12 — committed JSON result files + narrative gate reports | met | `results/determinism.json`, `results/exp1.json`, `results/exp2.json`, `results/corpus-manifest.json`, `results/phase1-fixtures.json`, plus the two narrative gate reports `docs/gates/phase0-gate.md` (this document) and `docs/gates/phase1-gate.md` |

## Advisory-scope note on EXP-1 (AC-5)

EXP-1 ran at **tier-S advisory scale**: 2,000 edges and 100 patterns on the user's 8 GB machine (`measurement_environment.label` = `advisory`, `is_reference_profile` = false). The tier-L envelope (~2–5 M edges, FR-6) and any `reference`-labelled certification against the 32 GB reference profile are deferred to Phase 8 (PLAN §5.6.8, NFR-1). The `advisory-pass` verdict therefore informs the storage decision but certifies nothing about reference-profile performance.

## Gate-condition mapping (PLAN §5.6.8, Phase-0 gate)

| Gate condition | Outcome |
|---|---|
| Deterministic generator, byte-identical at same seed | PASS (`results/determinism.json`, tier L, digest `860e55f7…`) |
| Injection manifest as ground truth, 60/30/10 mix, ≥ 25 defects/rule at tier L | PASS (`evaltools/corpus/injection-manifest.json`) |
| 20-commit scripted series, seven change kinds | PASS (`evaltools/corpus/commit-series.json`) |
| EXP-1 executed with recorded p95 + env block + escalation rungs | PASS as `advisory-pass` (`results/exp1.json`) |
| EXP-2 executed with recorded per-callsite depth/template/tier + precision | **FAIL** (`results/exp2.json`, precision 0.0 / recall 0.0) — Phase-0 gate NOT PASSED on this condition |
| Real-corpus checkouts pinned (repo, SHA, licence, date) | PASS (`results/corpus-manifest.json`, bullmq v6.4.2 @ `f42514c3…`, MIT) |
| Machine-readable evidence + narrative gate report committed | PASS (`results/*` + this report + `docs/gates/phase1-gate.md`) |
