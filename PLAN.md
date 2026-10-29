# PLAN.md — Redis Engineering Intelligence Runtime

**Status:** Architecture specification, Sections 1–4 authored (backend domain); Sections 5–6 follow in a subsequent increment (systems-architect domain).
**Incremental-write protocol (FR-2):** this file is written in sequential increments — Increment 1: header + Sections 1–2; Increment 2: Sections 3–4; Increment 3 (owner: systems_architect): Sections 5–6 + on-disk completeness verification.
**Decision-tag legend (FR-4):** `[RECOMMENDED]` design-backed, ready for approval · `[PROVISIONAL]` sensible default, tunable · `[EXPERIMENT REQUIRED]` gated on a defined experiment (EXP-1..4) · `[APPROVAL REQUIRED]` deviates from or extends an approved position — needs user sign-off.
**Shared interface:** the **Finding Contract v1.0.0** (§2.6) is the versioned interface cited by the CLI/reporting surface (§1.4) and the learning loop (§4.7); the **Section-4 provider contract** (§4.2) is the single source for TaskNode budget/retry fields and the `mode != DETERMINISTIC` guard (§3.5).

---

# SECTION 1 — Executive Summary, Decision Analysis, Adversarial Self-Review

## 1.1 System summary

The Redis Engineering Intelligence Runtime is a local, single-user Python service that ingests a TS/Node or Python repository, builds a deterministic intermediate representation (IR) of every Redis interaction — which functions touch which keys, with which commands, TTLs, and invalidation relationships — and answers natural-language engineering questions by combining **deterministic evidence** (AST-derived facts, static analysis findings) with **budgeted LLM reasoning** only where deterministic evidence is absent. Every claim in a report carries an epistemic tier (§1.2, FR-8) and a cost entry, so the system can prove both *what it knows* and *what it spent to know it*. Storage is one SQLite file (WAL mode) with recursive-CTE graph traversals; no server, no graph database, no vector store at MVP. Full index of a ~1M-LOC repo ≤ 10 min; incremental re-index after a commit ≤ 5 s; deterministic queries p95 ≤ 2 s. The MVP analyzer set is INV-002, TTL-001, NS-003, RACE-004, validated against the BullMQ (TS) and rq (Python) corpora. `[RECOMMENDED]`

## 1.2 Epistemic tier definitions (FR-8 — six tiers, exhaustive and exclusive)

Every claim, edge, and finding stored or emitted by the runtime is typed into **exactly one** of six tiers; no quiet upgrade of a model guess into an established fact ever occurs (upgrades happen only via re-derivation or the human-gated `learn` workflow, §4.7):

| Tier | Definition |
|---|---|
| `DETERMINISTIC_FACT` | Derived by a deterministic tool (parser, resolver, analyzer) from repository bytes alone; reproducible bit-for-bit given the same inputs and tool versions. |
| `STATIC_INFERENCE` | Derived by deterministic logic that goes beyond direct syntax (interprocedural resolution, wrapper propagation, alias analysis); still reproducible, but carries analysis assumptions in its evidence. |
| `MODEL_HYPOTHESIS` | Produced or influenced by an LLM call; admissible only after deterministic post-call verification (§4.1) and never above this tier from a model path. |
| `RUNTIME_OBSERVATION` | Measured against a live Redis/runtime instance; explicitly isolated from default static runs (non-goal at MVP). |
| `VERIFIED_OUTCOME` | A claim confirmed by runtime observation or by the human `learn` gate (§4.7); the only tier above `MODEL_HYPOTHESIS`. |
| `UNKNOWN` | An explicitly represented gap: unresolvable expression, unsupported syntax, denied evidence, or budget exhaustion. A typed answer, never silence and never a guess (FR-10). |

Storage-wide, every claim-bearing row carries `epistemic TEXT NOT NULL` with a CHECK over exactly these six values (§2.4 DDL).

## 1.3 Top 3 architectural decisions

| # | Decision | Rationale (concrete) | Status |
|---|----------|----------------------|--------|
| A1 | **Demand-driven runtime (Option 2 below)**: deterministic IR + analyzers always built; LLM reasoning allocated per-question via a budgeted control loop, not pre-computed summaries | Full-IR + 4-analyzer pass over 1M LOC is cheap (no LLM tokens); the expensive resource (LLM tokens) is spent only on questions whose answers need it. Options 1 and 3 fail on completeness or complexity respectively (§1.6). | [RECOMMENDED] |
| A2 | **Single-file SQLite (WAL) as the only persistent store; IR entities + typed graph edges as relational tables traversed with recursive CTEs; no separate vector DB** | One `runtime.db` file: zero ops, copyable, diffable, transactional with findings. Key graphs are shallow (≤4 hops: code unit → key expression → invalidation rule → affected code unit), exactly what recursive CTEs do well. Vectors deferred: lexical (BM25/FTS5) + structural centrality covers MVP retrieval; adding embeddings later is an additive migration, not a redesign. | [RECOMMENDED] |
| A3 | **Epistemic-tiered evidence architecture (§1.2) enforced by the Finding Contract (§2.6)**: every finding/retrieval artifact carries tier, confidence, verification method; deterministic analyzers are the only producers of `DETERMINISTIC_FACT`/`STATIC_INFERENCE`; LLM output is always `MODEL_HYPOTHESIS` until post-call deterministic verification; unresolved items are `UNKNOWN` | This is the mechanism that makes the hard honesty rules *structurally* satisfiable rather than a prompt-time promise: no fabricated latency numbers, no unverifiable claims presented as facts, no invented API names, no cross-analyzer sharing without provenance, full evidence trail. It also enables honest "partial report" output when budgets are exhausted. | [RECOMMENDED] |

## 1.4 Exact MVP boundary

- **Initial language (exactly one, per request §2.1):** TypeScript/Node on the server side — parsed with tree-sitter (pinned `tree-sitter-language-pack` wheels; `.tsx` via the separate TSX grammar; grammar pinned ≈ tree-sitter core 0.23.x). Python is **not** a second MVP frontend: it enters as first-class corpus evidence validating the language-agnostic IR (user answer q1 reconciled with request §2.1), and its frontend lands in a later phase with the redis-py pattern catalog. `[RECOMMENDED]`
- **Supported client patterns:** ioredis + node-redis v4/v5. Construction forms: `new Redis(options)`, `createClient()`, `createCluster()`. Command table: `get/set/setex/mset/del/unlink/expire/ttl/keys/scan/hget/hset/hgetall/publish/subscribe/pipeline/multi/exec/eval/register_script`; version-aware (node-redis has no `.pipeline()`; `multi()` may act as pipeline). **Wrapper propagation (round-2 correction, supersedes the one-hop assumption):** wrapper-propagation edges in the IR carry a **`DEPTH` attribute**; analyzers resolve wrappers to **depth 2** — verified against BullMQ, whose client construction is `RedisConnection` (`src/classes/redis-connection.ts`) → Proxy adapter (`src/classes/ioredis-client.ts`) → raw ioredis, i.e. two wrapper layers. Depth ≥ 3 or dynamically constructed clients escalate to `MODEL_HYPOTHESIS` candidate or `UNKNOWN` — never silently dropped. `[RECOMMENDED]`, depth-distribution measurement `[EXPERIMENT REQUIRED]` (EXP-2).
- **CLI interface:** `redis-intel index [--full|--since <ref>]`, `redis-intel ask "<question>" [--mode deterministic|constrained|advanced]`, `redis-intel findings [--rule ID] [--lifecycle S]`, `redis-intel cost [--run ID]`, `redis-intel doctor [--security]`, `redis-intel learn` (offline, human-gated; §4.7). `[RECOMMENDED]`

## 1.5 Explicit first-release non-goals (with revisit triggers)

| Non-goal | Trigger to revisit |
|---|---|
| Source patching / automated remediation (§2.9 findings carry remediation guidance only) | A user workflow demonstrates patch-application is demanded; then it is a new subsystem behind the human gate, never part of the analyzer. |
| Second MVP frontend language (Python frontend) | After the TS frontend passes its Phase gates and the bilingual corpus proves IR language-agnosticism (Phase roadmap, §6). |
| Vector embeddings / semantic retrieval | EXP-measured lexical recall shortfall on the corpora (§2.8 states the exact threshold). |
| Graph database / vector store / distributed services | A documented, measured failure of the SQLite recursive-CTE baseline against NFR-3 (§1.8 item 1 escalation gate). |
| LangGraph or agent frameworks | Control-loop state machine can no longer be expressed in ≤7 states without semantic loss, or >3 distinct orchestration topologies are required (§1.8 item 3). |
| AgentField / service deployment | Any of the three pre-declared triggers (§1.8 item 4). |
| Runtime/live-Redis observation | Explicit user request; `RUNTIME_OBSERVATION` stays an isolated tier until then. |
| MCP server / coding-agent plugin / prompt-stuffing CLI | Prohibited by design (FR-7); not revisitable within this architecture's charter. |

## 1.6 Three-option comparison matrix

| Dimension | Option 1: Minimal deterministic baseline (IR + 4 analyzers + lexical search, no LLM loop) | **Option 2: Demand-driven runtime (Option 1 + budgeted control loop, task graph, conditional LLM escalation) — selected** | Option 3: Heavyweight distributed (pre-computed LLM summaries per unit, vector store, LangGraph-style agent mesh) |
|---|---|---|---|
| **Correctness** | Findings are 100% deterministic and reproducible, but open questions (e.g. "does this pub/sub channel ever get consumed?") that need cross-file reasoning or judgment go unanswered — coverage ceiling | Deterministic facts stay deterministic; LLM fills only the residual question space, each answer tier-tagged and verified against the IR (a claimed "consumer" must resolve to a code unit via the key graph). Correctness = Option 1 inside the verified envelope + honest `UNKNOWN` gaps outside | Pre-computed summaries embed stale or invented facts at index time; no evidence trail per claim; correctness degrades silently as code drifts between re-indexes |
| **Token efficiency** | Zero tokens; but every question is either fully answerable cheaply or fully blocked — all-or-nothing | Tokens spent proportional to question difficulty; hard caps with partial-report fallback; savings proven by the FR-25 ledger (§4.5) | Worst: tokens burned at index time on summaries for units nobody ever queries (speculative cost), then burned again at query time on re-verification |
| **Latency (p95)** | ≤ 2 s for any supported query, but many queries return "cannot answer" | Deterministic-first pipeline: lexical/IR retrieval + cache lookup typically ≤ 2 s; LLM escalation adds seconds only for the minority of questions (per-call budget-bounded) | p95 dominated by LLM round-trips; 10–30 s common for first-touch questions; index-time LLM cost pushes incremental re-index past the ≤5 s target |
| **Incremental speed** | Fastest possible (pure re-parse + rule re-run) | Same incremental path (shared IR invalidation, §2.11); question-side costs are on-demand only | Must re-summarize affected units through the LLM on every commit → incremental re-index is LLM-bound, violates ≤5 s at any nontrivial change-set |
| **Complexity** | Minimal: parser + SQLite + 4 rule engines + search index | Moderate: adds control loop, task graph, retrieval scoring, provider adapter — all in-process, no infrastructure | Highest: embedding pipeline, vector store maintenance, summarization jobs, agent framework |
| **Testability** | Trivial: golden-file tests on analyzers and IR | Deterministic core testable with golden files; control loop testable with scripted LLM fakes + fixed seeds; provider adapter behind one interface | Summaries are non-deterministic at index time → no golden files; vector recall non-deterministic; agent mesh untestable end-to-end without live LLM |
| **Model independence** | N/A (no model) | Strong: provider adapter (OpenAI/Anthropic via structured outputs), no model-specific logic above the adapter; tier labels independent of provider | Weak: prompt-cache layout and summary format couple output quality to one provider's behaviour |

**Selection: Option 2.** Option 1 is retained as the *degraded mode* of Option 2 (control loop with zero LLM budget = Option 1), which is also the deterministic-mode and provider-disabled fallback (§4.4, §4.2.5). `[RECOMMENDED]`

## 1.7 Defensible-advantage ranking vs. a raw coding agent (ordered by implementation cost vs engineering value)

1. **Deterministic Redis interaction IR + 4 static analyzers** — highest value, near-zero marginal cost: a raw agent re-derives key↔code relationships from scratch per question (slow, error-prone); here they are precomputed, queryable in ms, and audit-provable.
2. **Incremental invalidation (≤5 s re-index)** — a raw agent re-reads everything or trusts stale memory; the runtime proves freshness with content hashes and propagates exactly the dirty subgraph.
3. **Epistemic tiering + evidence trail (FR-8)** — a raw agent states claims with unbounded confidence; every runtime claim is tiered, sourced to a finding ID, and reproducible.
4. **Budgeted LLM escalation with cost ledger (FR-25)** — a raw agent spends unbounded tokens; here every model call is justified by a missing-evidence calculation and accounted per question.
5. **Bounded, scored context assembly** — a raw agent stuffs whole files; retrieval returns scored, deduplicated, budget-sized evidence slices with provenance.
6. **Reproducible findings store with lifecycle** — findings are re-validated on commit (not silently stale), supporting regression-style checks a raw agent cannot offer.

## 1.8 Adversarial self-review — 10 mandated failure modes and their preventing constraints

| # | Failure mode | Design constraint that prevents it |
|---|---|---|
| 1 | Premature graph DB adoption | Storage is SQLite-only with recursive CTEs (§2.7); a graph DB requires a documented traversal-latency failure against NFR-3 via the EXP-1 escalation ladder (§2.10) — an explicit, measured upgrade gate, not a default. |
| 2 | Vector bloat / premature embeddings | MVP retrieval = lexical (BM25/FTS5 over symbols) + structural centrality over the key graph; embeddings enter only after the measured lexical-recall threshold of §2.8 is crossed on the corpora; vectors would live in the same SQLite file as an additive table, never a separate service. |
| 3 | LangGraph over-engineering | The control loop is one bounded, single-process Python loop with 7 explicit states (§3.1); no agent framework, no autonomous multi-agent mesh, no tool-use loops without a task-node contract. |
| 4 | AgentField lock-in | No agent-platform abstraction at MVP; the 3 triggers for revisiting are pre-declared: (a) >3 distinct orchestration topologies required by new features, (b) multi-runtime distribution requirement from a user, (c) the control-loop state machine can no longer be expressed in ≤7 states without semantic loss. |
| 5 | Token saving vs. recall degradation | FR-25 ledger + stopping rules (§3.6): budget cuts stop by *marginal information gain*, not by silent context truncation; every truncation is annotated in the report ("evidence omitted: X, cost cap hit"), and EXP-4 measures answer quality vs token spend on the corpus question set. |
| 6 | Unverified model caching | Cached knowledge entries (§3.5 step 2) store their source finding IDs and tier; a cache entry is invalidated by the same dirty-propagation as findings (§2.11) — a model-cached answer tied to a stale IR revision can never be served (composite-hash check on load). |
| 7 | Premature multi-language scope | MVP parses TS/Node (TSX via separate tree-sitter grammar) with pinned grammar wheels; Python is corpus evidence, not a second frontend (§1.4); any further language requires a new grammar audit task, not a config flag. |
| 8 | Graph conflation (mixing call graph, data-flow graph, key-dependency graph into one edge soup) | Edges are **typed** (fixed `edge_type` enum) **and node-kinded** (`source_kind`/`target_kind` — §2.4); the five projections (call graph, key flow, read/write, invalidation, data dependency) are *views* over the one adjacency table, never separate stores; every traversal declares its edge-type whitelist and kind filters; Finding Contract validation rejects untyped edges. |
| 9 | Stale cache hits | Every derived artifact stores `content_hash` + revision anchors (§2.6 composite cache keys, §3.4 `freshness`); any read path checks hash-chain freshness first (§2.11); findings transition to `stale` on dirty propagation and are either re-validated or explicitly marked `stale` in output — never silently served. |
| 10 | Over-compressed context slices | Evidence packages carry a minimum-fidelity floor: each included slice keeps its full IR field set (key template, client, resolved TTL, span) even under budget pressure; compression drops *whole low-scored slices* (with annotation), never field-truncates a retained slice (§3.4, §4.3). |

---

# SECTION 2 — System Design: IR, Canonical Schemas, Storage, Invalidation

## 2.1 Mermaid diagram (a): high-level architecture

```mermaid
flowchart TD
    CLI["C-8 CLI surface<br/>index · ask · findings · cost · doctor · learn"] --> CTRL["C-4 Control loop + Task Execution Graph<br/>budget ledger, mode guard"]
    CLI --> GOV["C-7 Security / governance<br/>sanitization, redaction, EgressGate, audit"]
    CTRL --> RET["C-5 Retrieval / persistence / invalidation<br/>SQLite WAL store, recursive CTEs"]
    CTRL --> ANA["C-3 Deterministic analyzer framework<br/>INV-002 · TTL-001 · NS-003 · RACE-004"]
    CTRL --> RSN["C-6 Bounded reasoning provider layer<br/>PromptBuilder · OutputVerifier · adapters"]
    ANA --> IR["C-2 Redis IR extraction<br/>14 entities, typed edges (DEPTH on wrapper edges)"]
    FE["C-1 Ingestion / language frontend<br/>tree-sitter TS/TSX, git diff reader"] --> IR
    IR --> RET
    GOV -.->|"redacted evidence only"| RSN
    RSN --> VER["Deterministic OutputVerifier<br/>schema · IrIds · verbatim quotes · tier ceiling"]
    VER --> CTRL
    RET --> FSTORE["Finding store + cost ledger<br/>Finding Contract v1.0.0"]
    CTRL --> REP["Report generator<br/>tier-annotated, partial-report capable"]
```

Edge payload contracts: `CLI→C-4` `CommandRequest`; `C-4→C-1` `IngestPlan{files, hunks}`; `C-1/C-2→C-5` `IRDelta` (row sets of §2.4); `C-2→C-3` `CodeUnitSlice`; `C-3→Finding store` `Finding` (§2.6); git watcher→C-1 `DiffEvent`; `C-4→C-5` `RetrievalQuery` (§3.4); `C-5→C-4` `EvidencePackage`; `C-4→C-6` evidence package only — `PromptBuilder.build(evidence)` is owned by §4.2 and redaction is internal to it; `C-6→Verifier` `ProviderResult`; `Verifier→C-4` `VerificationReport`; `C-4→ReportGen` `InvestigationResult`; all components → cost ledger `CostEntry` (FR-25).

## 2.2 Mermaid diagram (b): Redis IR entity-relationship model

```mermaid
erDiagram
    revisions ||--o{ files : "first_seen / last_seen"
    files ||--o{ scopes : "contains"
    files ||--o{ symbols : "declares"
    scopes ||--o{ symbols : "owns"
    scopes ||--o{ ops : "issues"
    ops ||--o| key_exprs : "targets (key_expr_id FK)"
    ops ||--o| ttl_sources : "ttl_source_id FK"
    ops ||--o{ serializers : "value boundary at op"
    scopes ||--o{ clients : "constructs (wrapper_depth, conn_config redacted)"
    scopes ||--o{ namespaces : "declares prefix"
    key_exprs }o--o{ namespaces : "prefix membership via edges"
    edges {
        int edge_id PK
        string edge_type "CALLS|KEY_FLOW|READS|WRITES|DELETES|EXPIRES|INVALIDATES|DATA_FLOW|IMPORTS"
        string source_kind "scope|symbol|op|key_expr|client|namespace|file"
        int source_id
        string target_kind "scope|symbol|op|key_expr|client|namespace|file"
        int target_id
        json evidence_json "spans + provenance + wrapper DEPTH on wrapper-propagation edges"
        string epistemic "6-tier CHECK"
    }
    edges }o--|| scopes : "node space (6-column shape)"
    edges }o--|| symbols : "node space"
    edges }o--|| ops : "node space"
    edges }o--|| key_exprs : "node space"
    edges }o--|| clients : "node space"
    edges }o--|| namespaces : "first-class node kind"
    findings }o--|| analysis_artifacts : "cache_key FK"
    feedback }o--|| findings : "human verdicts, dev-split only"
    schema_meta ||--|| store_manifest : "integrity pairing"
```

Notes: (1) the **one `edges` adjacency table** is the single node-space join domain — all five projections (§2.5) are views over it, so a traversal addresses scopes, symbols, ops, key_exprs, clients and namespaces uniformly; (2) `namespaces` is a **first-class node kind**, not an annotation; (3) wrapper-propagation `IMPORTS`/`KEY_FLOW` edges carry the **DEPTH attribute** in `evidence_json` (round-2 correction: bullmq verified at depth 2 — `RedisConnection` → `ioredis-client` Proxy → raw ioredis); analyzers resolve wrappers to depth 2; deeper or dynamically constructed indirection escalates to `MODEL_HYPOTHESIS`/`UNKNOWN`, never a silent drop; (4) the `clients.conn_config_json` column is redacted at IR build time — secrets are never stored (§4.7).

## 2.3 FR-11 entity inventory → canonical schema mapping (all 14 entities)

| # | FR-11 entity | Storage realization (storage-normative DDL, §2.4) |
|---|---|---|
| 1 | Repository Revision | `revisions` |
| 2 | File | `files` (+ `files_fts`-style content-hash index for rename detection) |
| 3 | Scope/Callable | `scopes` (module/function/method/class/lambda/arrow/script) |
| 4 | Symbol / Call Edge | `symbols`; call relations as `edges(edge_type='CALLS')` |
| 5 | Redis Client Instance | `clients` (`client_library`, `construction`, `wrapper_depth`) |
| 6 | Connection Config | `clients.conn_config_json` — **redacted at IR build** |
| 7 | Command/Operation (Read/Write/Delete/Expire/Pipeline/Transaction/Lua/PubSub) | `ops` (`kind` CHECK over the 8 kinds; `method` = concrete client method) |
| 8 | Key Expression (literal vs interpolated template) | `key_exprs` (`kind` ∈ literal/template/dynamic_unknown; `slots_json` interpolation slots) |
| 9 | Namespace/Prefix | `namespaces` (first-class; node kind in `edges`) |
| 10 | Value Serialization Boundary | `serializers` (json/msgpack/string/buffer/unknown, attached per op) |
| 11 | TTL Source | `ttl_sources` (`expression`, `resolved_seconds` NULL when unresolvable — stays honest) |
| 12 | Invalidation Edge | `edges(edge_type='INVALIDATES')` |
| 13 | Data Flow Edge | `edges(edge_type='DATA_FLOW')` |
| 14 | Test Reference | Test files are `files`/`scopes` rows whose paths match the test-path convention; `edges(edge_type='CALLS'/'IMPORTS', evidence_json.test_ref=true)` link test scopes to production scopes; consumed by finding validation strategy (§2.9). Reuses existing tables — no dedicated table at MVP. `[RECOMMENDED]` |

## 2.4 Storage-normative SQL DDL (SQLite) — canonical tables

The TS/Python data contracts (§2.9 walkthrough serialization) are the **serialization mirror**; the SQL DDL below is **storage-normative**. Engine: SQLite, one database file per analyzed repo, **WAL mode, stdlib `sqlite3`, one writer process** (C-5 store is the only SQL choke point). Every claim-bearing row carries `epistemic TEXT NOT NULL` with the six-tier CHECK (§1.2). Identifiers are integer PKs (`INTEGER PRIMARY KEY` = rowid). Timestamps are UTC ISO-8601 text. No floats except FR-16 `confidence`/`probability` (0..1, CHECK-bounded). `[RECOMMENDED]`

```sql
-- 1.0 Meta / revision counter
CREATE TABLE schema_meta (
  id                  INTEGER PRIMARY KEY CHECK (id = 1),
  db_revision_counter INTEGER NOT NULL DEFAULT 0,       -- bumped once per canonical write tx
  ir_schema_version   TEXT NOT NULL,                    -- SemVer of the IR schema (FR-11)
  frontend_version    TEXT NOT NULL,                    -- redis_intel frontend package version
  last_full_revision  INTEGER,                          -- revision_id of last successful full index
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- 1.1 Repository revisions
CREATE TABLE revisions (
  revision_id       INTEGER PRIMARY KEY,
  git_ref           TEXT NOT NULL,
  parent_revision_id INTEGER REFERENCES revisions(revision_id),
  kind              TEXT NOT NULL CHECK (kind IN ('full','incremental')),
  file_count        INTEGER NOT NULL CHECK (file_count >= 0),
  indexed_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE (git_ref)
);

-- 1.2 Files
CREATE TABLE files (
  file_id         INTEGER PRIMARY KEY,
  path            TEXT NOT NULL,                        -- repo-relative, POSIX separators
  content_hash    TEXT NOT NULL,                        -- sha256 hex of normalized source text
  grammar_id      TEXT NOT NULL CHECK (grammar_id IN ('typescript','tsx','javascript','python')),
  grammar_version TEXT NOT NULL,                        -- pinned wheel version (cache-key input)
  size_bytes      INTEGER NOT NULL CHECK (size_bytes >= 0),
  loc             INTEGER NOT NULL CHECK (loc >= 0),
  first_seen_revision INTEGER NOT NULL REFERENCES revisions(revision_id),
  last_seen_revision  INTEGER NOT NULL REFERENCES revisions(revision_id)
);
CREATE UNIQUE INDEX idx_files_path ON files(path);
CREATE INDEX idx_files_content_hash ON files(content_hash);

-- 1.3 Scopes / callables
CREATE TABLE scopes (
  scope_id       INTEGER PRIMARY KEY,
  file_id        INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
  kind           TEXT NOT NULL CHECK (kind IN ('module','function','method','class',
                                               'lambda','arrow','script')),
  name           TEXT NOT NULL,                         -- qualified: 'CacheService.getUser'
  signature_hash TEXT NOT NULL,                         -- sha256 of normalized signature (FR-23)
  start_line     INTEGER NOT NULL CHECK (start_line >= 1),
  end_line       INTEGER NOT NULL CHECK (end_line >= start_line),
  epistemic      TEXT NOT NULL CHECK (epistemic IN
                 ('DETERMINISTIC_FACT','STATIC_INFERENCE','MODEL_HYPOTHESIS',
                  'RUNTIME_OBSERVATION','VERIFIED_OUTCOME','UNKNOWN'))
);
CREATE INDEX idx_scopes_file ON scopes(file_id);
CREATE INDEX idx_scopes_name ON scopes(name);

-- 1.4 Symbols
CREATE TABLE symbols (
  symbol_id  INTEGER PRIMARY KEY,
  file_id    INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
  scope_id   INTEGER REFERENCES scopes(scope_id) ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK (kind IN ('variable','parameter','property',
                                           'function','class','import','unknown')),
  name       TEXT NOT NULL,
  epistemic  TEXT NOT NULL CHECK (epistemic IN
             ('DETERMINISTIC_FACT','STATIC_INFERENCE','MODEL_HYPOTHESIS',
              'RUNTIME_OBSERVATION','VERIFIED_OUTCOME','UNKNOWN'))
);
CREATE INDEX idx_symbols_scope ON symbols(scope_id);
CREATE INDEX idx_symbols_file  ON symbols(file_id);
CREATE INDEX idx_symbols_name  ON symbols(name);

-- 1.5 Edges — the ONE adjacency table; five projections are views over it
CREATE TABLE edges (
  edge_id      INTEGER PRIMARY KEY,
  source_kind  TEXT NOT NULL CHECK (source_kind IN ('scope','symbol','op','key_expr',
                                                    'client','namespace','file')),
  source_id    INTEGER NOT NULL,
  edge_type    TEXT NOT NULL CHECK (edge_type IN
               ('CALLS','KEY_FLOW','READS','WRITES','DELETES','EXPIRES',
                'INVALIDATES','DATA_FLOW','IMPORTS')),
  target_kind  TEXT NOT NULL CHECK (target_kind IN ('scope','symbol','op','key_expr',
                                                    'client','namespace','file')),
  target_id    INTEGER NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',             -- spans + provenance + wrapper DEPTH attribute
  epistemic    TEXT NOT NULL CHECK (epistemic IN
               ('DETERMINISTIC_FACT','STATIC_INFERENCE','MODEL_HYPOTHESIS',
                'RUNTIME_OBSERVATION','VERIFIED_OUTCOME','UNKNOWN'))
);
CREATE INDEX idx_edges_type_source ON edges(edge_type, source_kind, source_id, target_kind, target_id);
CREATE INDEX idx_edges_type_target ON edges(edge_type, target_kind, target_id, source_kind, source_id);

-- 1.6 Redis operations
CREATE TABLE ops (
  op_id         INTEGER PRIMARY KEY,
  file_id       INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
  scope_id      INTEGER NOT NULL REFERENCES scopes(scope_id) ON DELETE CASCADE,
  client_id     INTEGER REFERENCES clients(client_id) ON DELETE SET NULL,
  kind          TEXT NOT NULL CHECK (kind IN
                ('READ','WRITE','DELETE','EXPIRE','PIPELINE','TRANSACTION',
                 'LUA_SCRIPT','PUBSUB')),               -- FR-11 Operation set
  method        TEXT NOT NULL,                          -- 'get','setex','hset','publish',...
  key_expr_id   INTEGER REFERENCES key_exprs(key_expr_id) ON DELETE SET NULL,
  args_json     TEXT NOT NULL DEFAULT '[]',
  ttl_source_id INTEGER REFERENCES ttl_sources(ttl_source_id) ON DELETE SET NULL,
  line          INTEGER NOT NULL CHECK (line >= 1),
  epistemic     TEXT NOT NULL CHECK (epistemic IN
                ('DETERMINISTIC_FACT','STATIC_INFERENCE','MODEL_HYPOTHESIS',
                 'RUNTIME_OBSERVATION','VERIFIED_OUTCOME','UNKNOWN'))
);
CREATE INDEX idx_ops_scope    ON ops(scope_id, kind);
CREATE INDEX idx_ops_key_expr ON ops(key_expr_id);
CREATE INDEX idx_ops_client   ON ops(client_id);
CREATE INDEX idx_ops_file     ON ops(file_id);

-- 1.7 Key expressions
CREATE TABLE key_exprs (
  key_expr_id INTEGER PRIMARY KEY,
  file_id     INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
  scope_id    INTEGER NOT NULL REFERENCES scopes(scope_id) ON DELETE CASCADE,
  kind        TEXT NOT NULL CHECK (kind IN ('literal','template','dynamic_unknown')),
  template    TEXT NOT NULL,                            -- 'sess:{userId}' | literal 'sess:1'
  slots_json  TEXT NOT NULL DEFAULT '[]',               -- [{name,span,symbol_id}]
  line        INTEGER NOT NULL CHECK (line >= 1),
  epistemic   TEXT NOT NULL CHECK (epistemic IN
              ('DETERMINISTIC_FACT','STATIC_INFERENCE','MODEL_HYPOTHESIS',
               'RUNTIME_OBSERVATION','VERIFIED_OUTCOME','UNKNOWN'))
);
CREATE INDEX idx_key_exprs_template ON key_exprs(template);
CREATE INDEX idx_key_exprs_scope    ON key_exprs(scope_id);

-- 1.8 Clients / namespaces / serializers / ttl_sources
CREATE TABLE clients (
  client_id       INTEGER PRIMARY KEY,
  file_id         INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
  scope_id        INTEGER NOT NULL REFERENCES scopes(scope_id) ON DELETE CASCADE,
  client_library  TEXT NOT NULL CHECK (client_library IN ('ioredis','node_redis','redis_py','unknown')),
  construction    TEXT NOT NULL,                        -- 'new Redis' | 'createClient' | 'from_url'
  conn_config_json TEXT NOT NULL DEFAULT '{}',          -- redacted at IR build (secrets never stored)
  wrapper_depth   INTEGER NOT NULL DEFAULT 0 CHECK (wrapper_depth >= 0),  -- 0=direct; DEPTH attribute of wrapper edges (round-2)
  epistemic       TEXT NOT NULL CHECK (epistemic IN
                  ('DETERMINISTIC_FACT','STATIC_INFERENCE','MODEL_HYPOTHESIS',
                   'RUNTIME_OBSERVATION','VERIFIED_OUTCOME','UNKNOWN'))
);
CREATE INDEX idx_clients_file ON clients(file_id);

CREATE TABLE namespaces (
  namespace_id INTEGER PRIMARY KEY,
  file_id      INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
  scope_id     INTEGER NOT NULL REFERENCES scopes(scope_id) ON DELETE CASCADE,
  prefix       TEXT NOT NULL,                           -- 'sess:', 'cache:user:'
  epistemic    TEXT NOT NULL CHECK (epistemic IN
               ('DETERMINISTIC_FACT','STATIC_INFERENCE','MODEL_HYPOTHESIS',
                'RUNTIME_OBSERVATION','VERIFIED_OUTCOME','UNKNOWN'))
);
CREATE INDEX idx_namespaces_prefix ON namespaces(prefix);

CREATE TABLE serializers (
  serializer_id INTEGER PRIMARY KEY,
  op_id         INTEGER NOT NULL REFERENCES ops(op_id) ON DELETE CASCADE,
  method        TEXT NOT NULL CHECK (method IN ('json','msgpack','string','buffer','unknown')),
  epistemic     TEXT NOT NULL CHECK (epistemic IN
                ('DETERMINISTIC_FACT','STATIC_INFERENCE','MODEL_HYPOTHESIS',
                 'RUNTIME_OBSERVATION','VERIFIED_OUTCOME','UNKNOWN'))
);
CREATE INDEX idx_serializers_op ON serializers(op_id);

CREATE TABLE ttl_sources (
  ttl_source_id   INTEGER PRIMARY KEY,
  file_id         INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
  scope_id        INTEGER NOT NULL REFERENCES scopes(scope_id) ON DELETE CASCADE,
  expression      TEXT NOT NULL,                        -- source text of the TTL argument
  resolved_seconds INTEGER,                              -- NULL when unresolvable (stays honest)
  epistemic       TEXT NOT NULL CHECK (epistemic IN
                  ('DETERMINISTIC_FACT','STATIC_INFERENCE','MODEL_HYPOTHESIS',
                   'RUNTIME_OBSERVATION','VERIFIED_OUTCOME','UNKNOWN'))
);
CREATE INDEX idx_ttl_sources_scope ON ttl_sources(scope_id);
```

**Findings** (FR-16 contract in storage form; `finding_id` is content-addressed):

```sql
CREATE TABLE findings (
  finding_id            TEXT PRIMARY KEY,   -- sha256(rule_id|evidence_span|ir_revision)
  schema_version        TEXT NOT NULL,
  rule_id               TEXT NOT NULL,
  rule_version          INTEGER NOT NULL CHECK (rule_version >= 1),
  severity              TEXT NOT NULL CHECK (severity IN ('info','minor','major','critical')),
  confidence            REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  probability           REAL NOT NULL CHECK (probability >= 0 AND probability <= 1),
  impact                TEXT NOT NULL,
  epistemic             TEXT NOT NULL CHECK (epistemic IN
                        ('DETERMINISTIC_FACT','STATIC_INFERENCE','MODEL_HYPOTHESIS',
                         'RUNTIME_OBSERVATION','VERIFIED_OUTCOME','UNKNOWN')),
  location_json         TEXT NOT NULL,      -- [{path,start_line,start_col,end_line,end_col}]
  ir_evidence_json      TEXT NOT NULL,      -- ordered IrIds = full evidence path
  assumptions_json      TEXT NOT NULL DEFAULT '[]',
  missing_evidence_json TEXT NOT NULL DEFAULT '[]',
  remediation           TEXT,               -- guidance only; no source patching (FR-16)
  validation_strategy   TEXT,
  lifecycle             TEXT NOT NULL CHECK (lifecycle IN
                        ('suspected','supported','verified','rejected','resolved','stale')),
  cache_key             TEXT REFERENCES analysis_artifacts(cache_key) ON DELETE CASCADE,
  first_seen_revision   INTEGER NOT NULL REFERENCES revisions(revision_id),
  last_confirmed_revision INTEGER NOT NULL REFERENCES revisions(revision_id)
);
CREATE INDEX idx_findings_lifecycle ON findings(lifecycle);
CREATE INDEX idx_findings_rule      ON findings(rule_id, rule_version);
CREATE INDEX idx_findings_cache_key ON findings(cache_key);
```

**Feedback** (FR-29 Observe→Measure loop persistence) — **dev-corpus-only, human-gated**: rows are written only by the offline `learn` workflow from *human* developer verdicts; no automated writer exists. The `corpus_split` marker feeds the regression-fixture workflow; `holdout` rows are locked against benchmark leakage. This table never stores prompt content (egress audit is hash-only, §4.7). `[RECOMMENDED]`

```sql
CREATE TABLE feedback (
  feedback_id       INTEGER PRIMARY KEY,
  finding_id        TEXT NOT NULL REFERENCES findings(finding_id) ON DELETE CASCADE,
  verdict           TEXT NOT NULL CHECK (verdict IN
                    ('confirmed_false_positive','rejected','confirmed_real','resolved')),
  reason            TEXT NOT NULL,
  reviewer          TEXT NOT NULL,                      -- human identifier; no automation writes here
  corpus_split      TEXT NOT NULL CHECK (corpus_split IN ('holdout','train')),
  captured_revision INTEGER NOT NULL REFERENCES revisions(revision_id),
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_feedback_finding ON feedback(finding_id);
CREATE INDEX idx_feedback_split   ON feedback(corpus_split);
```

**Task graph state** (FR-18, all nine task-node fields persisted for request-scoped checkpointing):

```sql
CREATE TABLE task_graph_state (
  task_id               TEXT NOT NULL,
  request_id            TEXT NOT NULL,
  type                  TEXT NOT NULL CHECK (type IN
                        ('parse','ir','analyze','retrieve','reason','synthesize')),
  state                 TEXT NOT NULL CHECK (state IN
                        ('pending','running','done','failed','cancelled','skipped')),
  inputs_json           TEXT NOT NULL DEFAULT '[]',
  required_evidence_json TEXT NOT NULL DEFAULT '[]',
  depends_on_json       TEXT NOT NULL DEFAULT '[]',
  token_budget          INTEGER NOT NULL DEFAULT 0 CHECK (token_budget >= 0),  -- 0 = deterministic
  cache_key             TEXT,
  retry_max             INTEGER NOT NULL DEFAULT 0 CHECK (retry_max >= 0),
  timeout_ms            INTEGER CHECK (timeout_ms IS NULL OR timeout_ms > 0),
  provenance_json       TEXT NOT NULL DEFAULT '[]',    -- every step incl. provider calls (NFR-6 audit)
  updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY (request_id, task_id)
);
CREATE INDEX idx_teg_request ON task_graph_state(request_id, state);
```

## 2.5 Derived projections — five views over the one `edges` table

Zero divergence by construction (FR-12): analyzers and queries read views; nobody stores a second adjacency copy. `[RECOMMENDED]`

```sql
CREATE VIEW v_call_graph AS
  SELECT source_id AS caller_scope_id, target_id AS callee_scope_id, epistemic, evidence_json
  FROM edges WHERE edge_type = 'CALLS' AND source_kind = 'scope' AND target_kind = 'scope';

CREATE VIEW v_key_flow AS
  SELECT source_id AS from_node_scope_id, target_id AS to_key_expr_id, epistemic, evidence_json
  FROM edges WHERE edge_type = 'KEY_FLOW';

CREATE VIEW v_readwrite AS
  SELECT edge_type, source_id AS scope_id, target_kind, target_id, epistemic, evidence_json
  FROM edges WHERE edge_type IN ('READS','WRITES','DELETES');

CREATE VIEW v_invalidation AS
  SELECT source_id AS invalidator_node_id, source_kind, target_kind,
         target_id AS invalidated_key_expr_id, epistemic, evidence_json
  FROM edges WHERE edge_type = 'INVALIDATES';

CREATE VIEW v_data_dep AS
  SELECT source_id AS producer_node_id, source_kind, target_kind,
         target_id AS consumer_node_id, epistemic, evidence_json
  FROM edges WHERE edge_type = 'DATA_FLOW';
```

**FTS5** (external-content over `symbols`; rebuildable from canonical rows, FR-21):

```sql
CREATE VIRTUAL TABLE symbols_fts USING fts5(name, content='symbols', content_rowid='symbol_id');
CREATE TRIGGER symbols_fts_ai AFTER INSERT ON symbols BEGIN
  INSERT INTO symbols_fts(rowid, name) VALUES (new.symbol_id, new.name); END;
CREATE TRIGGER symbols_fts_ad AFTER DELETE ON symbols BEGIN
  INSERT INTO symbols_fts(symbols_fts, rowid, name) VALUES ('delete', old.symbol_id, old.name); END;
CREATE TRIGGER symbols_fts_au AFTER UPDATE OF name ON symbols BEGIN
  INSERT INTO symbols_fts(symbols_fts, rowid, name) VALUES ('delete', old.symbol_id, old.name);
  INSERT INTO symbols_fts(rowid, name) VALUES (new.symbol_id, new.name); END;
```

## 2.6 Composite cache-key manifest and db_revision_counter

**Canonical string** — each field joined with `\x1f` separators, arrays sorted; `cache_key = hex(sha256(canonical_string))` computed in the Python store layer (SQLite's stdlib build has no `sha256()` SQL function — the hash is computed in C-5 and stored, never recomputed in SQL). `[RECOMMENDED]`

```
canonical_string =
  content_hash ⧺ '\x1f' ⧺ grammar_id ⧺ '\x1f' ⧺ grammar_version ⧺ '\x1f'
  ⧺ ir_schema_version ⧺ '\x1f' ⧺ frontend_version ⧺ '\x1f'
  ⧺ join(sorted(analyzer_versions), ',') ⧺ '\x1f'
  ⧺ join(sorted(dep_hashes), ',')
```

```sql
CREATE TABLE analysis_artifacts (
  cache_key            TEXT PRIMARY KEY,
  artifact_kind        TEXT NOT NULL CHECK (artifact_kind IN ('file_ir_slice','finding_set')),
  file_id              INTEGER REFERENCES files(file_id) ON DELETE CASCADE,
  content_hash         TEXT NOT NULL,
  grammar_id           TEXT NOT NULL,
  grammar_version      TEXT NOT NULL,
  ir_schema_version    TEXT NOT NULL,
  frontend_version     TEXT NOT NULL,
  analyzer_versions_json TEXT NOT NULL,       -- sorted JSON array, e.g. ["INV-002@1","TTL-001@3"]
  dep_hashes_json      TEXT NOT NULL,         -- sorted JSON array of import-closure content hashes
  canonical_string     TEXT NOT NULL,         -- stored verbatim for auditability/debuggability
  created_revision     INTEGER NOT NULL REFERENCES revisions(revision_id),
  last_verified_revision INTEGER NOT NULL REFERENCES revisions(revision_id)
);
CREATE INDEX idx_artifacts_file ON analysis_artifacts(file_id);
CREATE INDEX idx_artifacts_kind ON analysis_artifacts(artifact_kind, last_verified_revision);
```

Invalidation semantics: a changed key template invalidates only artifacts whose `dep_hashes_json` (or own content hash) covers the file/region containing that `key_exprs` row; findings link to artifacts via `findings.cache_key`, so artifact eviction cascades finding staleness deterministically.

**`db_revision_counter`**: single-writer discipline makes a trigger unnecessary; the store layer runs, as the last statement inside every canonical-write transaction:

```sql
UPDATE schema_meta
SET db_revision_counter = db_revision_counter + 1,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')
WHERE id = 1;
```

Readers open a deferred read transaction; under WAL they get a consistent snapshot, and the counter read inside that snapshot is the **transient-cache epoch**: transient query cache key = `sha256(query_dsl) || ':' || db_revision_counter`. A cache hit is valid iff the cached entry's epoch equals the snapshot's counter. In-memory LRU (128 entries) + optional `.cache/` entries store the epoch alongside the payload; wholesale deletion is always safe (transient class, §2.7).

## 2.7 Storage classification, comparison, pragmas, bulk insert, recovery

**Storage classes (FR-21/AC-8):**
- **Canonical state** (must survive, single source of truth): all §2.4 tables; re-derivable only from repo + toolchain; `feedback` is canonical too (human verdicts are irreplaceable evidence — exported/re-imported across rebuilds).
- **Derived index** (rebuildable): the five projection views, `symbols_fts`, `analysis_artifacts`, `store_manifest` digests.
- **Transient cache** (safe to delete wholesale): in-memory LRU + `.cache/` query results keyed by `sha256(query_dsl) || ':' || db_revision_counter`; cached `MODEL_HYPOTHESIS` knowledge entries (hash-anchored, §3.5).

**Engine comparison (FR-21):** SQLite embedded relational (selected, A2) vs content-addressed filesystem blobs (rejected: no transactional findings/artifacts coupling, no CTE joins — viable only as the `.cache/` layer) vs hybrid local stores (rejected at MVP: two stores to keep consistent; revisited only via the EXP-1 escalation ladder). `[RECOMMENDED]`

**Connection pragmas** `[RECOMMENDED]`:

```sql
PRAGMA journal_mode = WAL;             -- readers never block the single writer
PRAGMA synchronous  = NORMAL;          -- canonical truth = re-parse, not the DB
PRAGMA foreign_keys = ON;              -- per-connection; store layer asserts it on open
PRAGMA busy_timeout = 5000;            -- second concurrent run → WAITING state
PRAGMA cache_size   = -65536;          -- 64 MB page cache (laptop envelope)
PRAGMA mmap_size    = 268435456;       -- 256 MB memory-mapped reads for CTE scans
PRAGMA temp_store   = MEMORY;          -- recursive CTE working tables in RAM
PRAGMA wal_autocheckpoint = 4000;
PRAGMA journal_size_limit = 67108864;
PRAGMA page_size    = 4096;            -- set on empty DB before first table
```

**Bulk-insert strategy (2–5M rows):** create schema *without* secondary indexes → bulk-load (parent-first insert order with `foreign_keys=ON`: files → scopes → symbols → key_exprs → clients → ttl_sources → ops → serializers → edges → findings → feedback; one transaction per ~200k rows, `executemany` chunks of 25k, `wal_checkpoint(PASSIVE)` between transactions) → `CREATE INDEX` each secondary index → `ANALYZE` → `wal_checkpoint(TRUNCATE)`. Expected: 5–25 s insert + 10–30 s index builds — inside NFR-1's 10 min alongside the 50–100 s parse. Incremental path: per changed file, one transaction (delete-old-rows via `ON DELETE CASCADE` + upsert + counter bump); ≤50 files/commit ⇒ ≤50 short transactions. `[RECOMMENDED]`

**Corruption recovery:** integrity guard table

```sql
CREATE TABLE store_manifest (
  revision_id           INTEGER PRIMARY KEY REFERENCES revisions(revision_id),
  table_row_counts_json TEXT NOT NULL,
  spot_digest           TEXT NOT NULL,   -- sha256 over per-table MIN(pk),MAX(pk),COUNT(*),sum(content_hash)
  checked_at            TEXT
);
```

Procedure: (1) on open `PRAGMA quick_check;` — any row other than `ok` ⇒ corrupted; (2) cheap drift check: recompute `spot_digest` vs `store_manifest`; (3) if corrupted: **never write in place** — quarantine the file as `<name>.corrupt-<utc-timestamp>`, create a fresh database, re-run `index --full` (canonical truth is the re-parse); export `feedback` rows to JSON and re-import before quarantine deletion; (4) stale/unknown revision journal or IR schema bump ⇒ full-rebuild fallback (same path without quarantine); (5) after rebuild: full `PRAGMA integrity_check;` + `store_manifest` rewrite, both logged in the provenance ledger. **Explicit full-rebuild fallback condition (FR-23):** any of — corrupted store; unknown/older schema revision; IR schema version bump; parser/analyzer version bump that changes the composite-key salt space — triggers full re-index (≤10 min budget). `[RECOMMENDED]`

## 2.8 Retrieval traversal SQL (FR-13) and query compilation (FR-22)

Node space is `(node_kind, node_id)` pairs; cycle guard uses the `path` string (`instr`) — conservative substring test; false positives only shorten a walk, never produce wrong rows.

**Q1 — role classification** (no recursion; writers / readers / deleters / TTL setters of a key pattern):

```sql
-- :key_pattern is a GLOB pattern, e.g. 'sess:*'
SELECT ke.template,
       o.kind,
       CASE o.kind
         WHEN 'WRITE'  THEN 'writer'
         WHEN 'READ'   THEN 'reader'
         WHEN 'DELETE' THEN 'deleter'
         WHEN 'EXPIRE' THEN 'ttl_setter'
         ELSE 'pipeline_transaction_lua_or_pubsub'
       END AS role,
       ts.expression AS ttl_expr, ts.resolved_seconds,
       o.epistemic, sc.name AS scope_name, fi.path AS file_path, o.line
FROM key_exprs ke
JOIN ops o     ON o.key_expr_id = ke.key_expr_id
JOIN scopes sc ON sc.scope_id   = o.scope_id
JOIN files  fi ON fi.file_id    = sc.file_id
LEFT JOIN ttl_sources ts ON ts.ttl_source_id = o.ttl_source_id
WHERE ke.template GLOB :key_pattern
ORDER BY role, fi.path, o.line;
```

**Q2 — recursive-CTE master traversal** (key pattern → all reachable scopes/symbols, callers up, callees/readers down, with evidence paths):

```sql
-- Parameters: :key_pattern (GLOB), :max_hops (default 3)
WITH RECURSIVE
seed_ops AS (
  SELECT o.op_id, o.scope_id, o.kind AS op_kind, o.epistemic
  FROM ops o
  JOIN key_exprs ke ON ke.key_expr_id = o.key_expr_id
  WHERE ke.template GLOB :key_pattern
),
reach(dir, node_kind, node_id, depth, path) AS (
  SELECT 'up'  , 'scope', scope_id, 0, 'scope:' || scope_id FROM seed_ops
  UNION
  SELECT 'down', 'scope', scope_id, 0, 'scope:' || scope_id FROM seed_ops
  UNION ALL
  SELECT r.dir,
         CASE r.dir WHEN 'up' THEN e.source_kind ELSE e.target_kind END,
         CASE r.dir WHEN 'up' THEN e.source_id   ELSE e.target_id   END,
         r.depth + 1,
         r.path || '|'
           || (CASE r.dir WHEN 'up' THEN e.source_kind ELSE e.target_kind END)
           || ':' || (CASE r.dir WHEN 'up' THEN e.source_id ELSE e.target_id END)
  FROM reach r
  JOIN edges e
    ON  e.edge_type IN ('CALLS','KEY_FLOW','DATA_FLOW')
    AND (CASE r.dir WHEN 'up' THEN e.target_kind ELSE e.source_kind END) = r.node_kind
    AND (CASE r.dir WHEN 'up' THEN e.target_id   ELSE e.source_id   END) = r.node_id
  WHERE r.depth < :max_hops
    AND instr(r.path,
          (CASE r.dir WHEN 'up' THEN e.source_kind ELSE e.target_kind END)
          || ':' || (CASE r.dir WHEN 'up' THEN e.source_id ELSE e.target_id END)) = 0
)
SELECT r.dir AS direction, r.depth AS hops, r.node_kind, r.node_id,
       COALESCE(sc.name, sy.name, ke.template) AS label,
       fi.path AS file_path, r.path AS evidence_path
FROM reach r
LEFT JOIN scopes    sc ON r.node_kind = 'scope'    AND sc.scope_id    = r.node_id
LEFT JOIN symbols   sy ON r.node_kind = 'symbol'   AND sy.symbol_id   = r.node_id
LEFT JOIN key_exprs ke ON r.node_kind = 'key_expr' AND ke.key_expr_id = r.node_id
LEFT JOIN files     fi ON fi.file_id = COALESCE(sc.file_id, sy.file_id, ke.file_id)
ORDER BY r.dir, r.depth, r.node_id;
```

**Q3 — invalidation paths** (pattern → key_exprs → INVALIDATES edges → invalidating scopes):

```sql
WITH RECURSIVE
seed_kx AS (SELECT key_expr_id FROM key_exprs WHERE template GLOB :key_pattern),
inv_walk(node_kind, node_id, depth, path) AS (
  SELECT 'key_expr', key_expr_id, 0, 'key_expr:' || key_expr_id FROM seed_kx
  UNION ALL
  SELECT e.source_kind, e.source_id, w.depth + 1,
         w.path || '|' || e.source_kind || ':' || e.source_id
  FROM inv_walk w
  JOIN edges e ON e.edge_type = 'INVALIDATES'
              AND e.target_kind = w.node_kind
              AND e.target_id   = w.node_id
  WHERE w.depth < :max_hops
    AND instr(w.path, e.source_kind || ':' || e.source_id) = 0
)
SELECT w.depth, w.node_kind, w.node_id,
       COALESCE(sc.name, ke.template) AS label, fi.path, w.path AS evidence_path
FROM inv_walk w
LEFT JOIN scopes    sc ON w.node_kind = 'scope'    AND sc.scope_id    = w.node_id
LEFT JOIN key_exprs ke ON w.node_kind = 'key_expr' AND ke.key_expr_id = w.node_id
LEFT JOIN files     fi ON fi.file_id = COALESCE(sc.file_id, ke.file_id);
```

**Compilation of the four RetrievalQuery kinds** `[RECOMMENDED]` (latency `[EXPERIMENT REQUIRED]` → EXP-1):

| `kind` | Example `subject`/`filters` | Compiled SQL |
|---|---|---|
| `symbol` | `subject='CacheService.getUser'`, `direction='up'`, `hops=3` | Q2 with `seed_ops` replaced by a single scope seed; `dir` fixed to the requested direction; no key_expr join. |
| `key_pattern` | `subject='sess:*'` | Q1 (roles) + Q2 (paths) + Q3 (invalidation), executed as one Python call issuing all three against one read snapshot. |
| `metadata` | `filters={'namespace':'cache:user:'}` or free-text symbol search | `SELECT * FROM namespaces WHERE prefix GLOB :prefix` joined to `key_exprs`/`ops` by scope; free-text via `SELECT rowid, name FROM symbols_fts WHERE symbols_fts MATCH :query`. |
| `graph_traversal` | `subject='<node_kind>:<id>'`, `hops=k`, `direction` | Q2's `reach` CTE verbatim with `seed_ops` replaced by the single seed node; `epistemic_gte` filter applied in Python against the fixed tier ladder (tiers are an ordered set, never sorted in SQL). |

Every returned row maps to a claim with its epistemic tier stamped; unresolvable subjects return a typed `unknowns` result (FR-10) — a miss is a typed gap, never silence. **No free-text LLM fallback exists** — deterministic indexes suffice for the MVP (FR-22). **Exact empirical threshold for adding vector embeddings later:** if measured lexical recall@10 on the bilingual corpus question set falls below **0.85** [PROVISIONAL] in the EXP-gated benchmark, an embeddings table is added to the same SQLite file as an additive migration; until then no vector store is built. `[EXPERIMENT REQUIRED]`

## 2.9 Deterministic analyzer framework (FR-14/15/16; AC-6)

**Analyzer contract fields** (every rule publishes all of them): `rule_id`, `rule_version`, required IR inputs (e.g. TTL-001 requires `ops`+`ttl_sources`), execution cost class (`O(files)` / `O(edges)` / `O(traversal_depth_k)`), confidence ceiling (deterministic analyzers emit only `DETERMINISTIC_FACT`/`STATIC_INFERENCE`, confidence 1.0 for pattern match), caching rules (findings are content-addressed via `analysis_artifacts.cache_key`), and regression-test fixtures (golden IR + expected finding set per rule). **Pattern detection is separated from severity scoring, impact estimation, and remediation generation** — a detector emits a normalized pattern match; scoring stages consume it. `[RECOMMENDED]`

**Ranked rule catalog (FR-15)** — the seven candidate categories ranked by engineering value, precision, implementation cost; **selected MVP subset: INV-002, TTL-001, NS-003, RACE-004** (4 of 7):

| Rank | Rule | Category | Value | Precision | Cost | MVP |
|---|---|---|---|---|---|---|
| 1 | INV-002 | Cache-aside invalidation gaps after source-of-truth writes | highest | high | medium | **yes** |
| 2 | TTL-001 | Missing / inconsistent TTLs | high | high | low | **yes** |
| 3 | NS-003 | Key namespace / interpolation mismatches | high | high | low | **yes** |
| 4 | RACE-004 | Non-atomic read-modify-write races | high | medium | medium | **yes** |
| 5 | SER-005 | Serialization mismatches | medium | medium | medium | deferred |
| 6 | LOOP-006 | Unbounded command loops (N+1 / hot keys) | medium | medium | high | deferred |
| 7 | POOL-007 | Connection pool leaks | lower | medium | high | deferred |

**Finding lifecycle statuses (FR-16):** `suspected` → `supported` → `verified` → `rejected` / `resolved` / `stale` (transition rules in §2.11). **Source patching is out of scope for the MVP** — findings carry remediation guidance and a validation-test strategy, never a patch. `[RECOMMENDED]`

## 2.10 Mermaid diagram (c): incremental invalidation / persistence lifecycle

```mermaid
flowchart TD
    A["git commit C1"] --> B["git diff --name-only HEAD~1<br/>+ hunk line ranges (-U0)"]
    B --> C["Map hunks to code units by span overlap"]
    C --> D{"unit_hash changed?"}
    D -->|"no"| E["Prune subtree: signature_hash unchanged<br/>only body re-analyzed (bounded work)"]
    D -->|"yes"| F["Mark DIRTY in run manifest<br/>findings → lifecycle 'suspected'"]
    F --> G["Forward-propagate along CALLS edges (BFS,<br/>visited-set memoized; depth cap 4)"]
    G --> H["Re-resolve ops → recompute key_exprs<br/>diff vs prior; changed key → invalidate<br/>INVALIDATES rules + READS closure (CTE)"]
    H --> I["Re-run 4 analyzers on dirty units only"]
    I --> J["Diff findings by finding_id:<br/>new / stale / resolved / re-supported transitions"]
    J --> K["Emit IRDelta: one tx per changed file<br/>(cascade delete + upsert)"]
    K --> L["Bump db_revision_counter<br/>(transient-cache epoch)"]
    L --> M["Update analysis_run hash chain<br/>(prev_run_id + merkle of unit hashes)"]
    M --> N{"quick_check + spot_digest OK?"}
    N -->|"yes"| O["Store consistent — done"]
    N -->|"no"| P["Quarantine .corrupt-<ts> → fresh DB →<br/>index --full (≤10 min) → re-import feedback"]
```

## 2.11 Invalidation algorithm (final form)

**Composite hashing strategy** `[RECOMMENDED]`:
- `file_hash = sha256(normalized source text)`; unit identity via `scopes.signature_hash = sha256(normalized signature)`; per-slice content hashes for code units; `ir_revision` tracked via `db_revision_counter` + `analysis_run` hash chain.
- Salt = `{grammar_id, grammar_version, ir_schema_version, frontend_version, sorted(analyzer_versions)}` — any toolchain bump changes every composite key at once (prevents stale caches across upgrades, failure mode 9). Concretely: the §2.6 `canonical_string` over `analysis_artifacts`.

**Dependency-DAG propagation on git diff** `[RECOMMENDED]` (as diagrammed in §2.10):
1. `git diff --name-only HEAD~1` → changed files; `git diff -U0` → hunk line ranges.
2. Map hunks → code units by span overlap. Unit dirty iff its content hash changed; **signature unchanged ⇒ prune subtree** — only the body re-analyzes, callers' signatures intact (bounded work — this is what makes ≤5 s feasible).
3. Dirty units forward-propagate along `CALLS` edges (BFS, visited-set memoized in the run manifest); each reachable unit is marked dirty, its findings transition to `suspected`.
4. For each dirty unit: re-resolve ops → recompute key_exprs → diff against prior; any changed key_expr invalidates its `INVALIDATES` rules and downstream consumers (READS closure, recursive CTE, depth cap 4).
5. Re-run the 4 analyzers only on dirty units; diff new findings vs prior by `finding_id` → `new / stale / resolved / re-supported` transitions.
6. Emit `IRDelta`; bump `db_revision_counter`; update the run hash chain (`prev_run_id` + merkle of unit hashes) → tamper-evident freshness.

**Stale-finding transitions** `[RECOMMENDED]`: `suspected → supported` on first read-acknowledgement; any dirty propagation touching its blast radius → `suspected`; after re-analysis: facts unchanged → back to `supported` with new `last_confirmed_revision`; facts changed → new finding, old one → `resolved` (superseded) or `stale` (evidence source vanished, e.g. file deleted → finding kept with `stale` + tombstone note, never silently dropped).

**Modified / renamed / deleted files, changed signatures, modified key templates, toolchain upgrades** — each maps to a composite-key field (§2.6), so stale findings are invalidated without rebuilding unaffected regions; the explicit full-rebuild fallback condition is stated in §2.7. `[RECOMMENDED]`

## 2.12 End-to-end code-to-IR walkthrough

*(This snippet is also the QA suite's first golden-file fixture.)*

Target bug profile: a cache-aside helper with **three simultaneous detectable defects** — missing TTL (TTL-001), key-namespace drift between writer and invalidator (NS-003), and a read-modify-write race that repopulates stale data (RACE-004) — plus one INV-002 consequence (stale listing view after an invalidation that misses derived keys).

```ts
// src/cache/userProfile.ts — illustrative walkthrough corpus (BullMQ-style client import assumed elsewhere)
import { redis } from "./redis";            // ioredis client, alias "redis"
import { db } from "../db/pool";
import { audit } from "../observability/audit";

export interface UserProfile { id: string; tenantId: string; name: string; email: string; plan: string; }

export async function getUserProfile(tenantId: string, userId: string): Promise<UserProfile> {
  const cacheKey = `profile:v1:${tenantId}:${userId}`;
  const cached = await redis.get(cacheKey);                    // redis_op #1: GET, ioredis
  if (cached) return JSON.parse(cached) as UserProfile;
  const rows = await db.query(
    "SELECT id, name, email, plan FROM users WHERE tenant_id = $1 AND id = $2", [tenantId, userId]);
  const profile = rows[0];
  if (!profile) throw new NotFoundError(`user:${userId}`);
  await redis.set(cacheKey, JSON.stringify(profile));          // redis_op #2: SET, no EX/PX arg → TTL-001
  return profile;
}

export async function updateUserPlan(tenantId: string, userId: string, plan: string): Promise<void> {
  const current = await getUserProfile(tenantId, userId);      // redis_op #1 revisited: read path inside write flow
  await db.query("UPDATE users SET plan = $1 WHERE tenant_id = $2 AND id = $3", [plan, tenantId, userId]);
  // (A) window between db.query above and redis.del below: concurrent getUserProfile re-caches pre-update row,
  //     then this DEL wipes it — but a second concurrent reader repopulates STALE data afterwards → RACE-004
  await redis.del(`profile:${userId}`);                        // redis_op #3: DEL — wrong template → NS-003 + INV-002
  await audit.log("plan.updated", { userId, previousPlan: current.plan });
}

export async function listProfilesByPlan(tenantId: string, plan: string): Promise<UserProfile[]> {
  const rows = await db.query("SELECT id FROM users WHERE tenant_id = $1 AND plan = $2", [tenantId, plan]);
  const profiles = await Promise.all(rows.map((r) => getUserProfile(tenantId, r.id)));  // N+1 cache reads
  return profiles;
}
```

**Serialized IR representation (outlined field-by-field, serialization mirror of §2.4 DDL):**
- `scopes` ×3: `getUserProfile`, `updateUserPlan`, `listProfilesByPlan`; each with `file_id` (sha256 of `src/cache/userProfile.ts`), span lines, `signature_hash` (e.g. `getUserProfile(tenantId: string, userId: string) → Promise<UserProfile>` normalized); no doc comment (itself a retrieval-quality note).
- `ops` ×3: #1 `{client: ioredis, kind: READ, method: "get", key_template: "profile:v1:{tenantId}:{userId}", slots: [tenantId, userId], ttl: none, span: L8}`; #2 `{kind: WRITE, method: "set", key_template: "profile:v1:{tenantId}:{userId}", ttl: none}` (TTL-001 trigger); #3 `{kind: DELETE, method: "del", key_template: "profile:{userId}", slots: [userId]}` (NS-003 trigger).
- `key_exprs` ×2 after template dedup: `K1 = "profile:v1:{tenantId}:{userId}"` (ops: read#1, write#2, effective TTL = none ← TTL-001 attaches here), `K2 = "profile:{userId}"` (ops: delete#3); both link to namespace nodes `N1="profile:v1:*"` / `N2="profile:*"`.
- `edges` (6-column shape): `WRITES: op#2→K1`; `READS: op#1→K1`; `INVALIDATES: op#3→K2`; `CALLS: updateUserPlan→getUserProfile`, `listProfilesByPlan→getUserProfile`; namespace membership edges `K1→N1`, `K2→N2`; wrapper-propagation edge for the `redis` import with `evidence_json.depth = 1` (module-level re-export of the ioredis client — within the resolvable depth-2 envelope). All with `provenance = "ast-resolver v1"`, `epistemic = DETERMINISTIC_FACT`.
- `serializers`: op#1 → `json` (the `JSON.parse(cached)` boundary), op#2 → `json` (`JSON.stringify`) — consistent, so no SER-005 finding.
- Invalidation rule (from DEL op #3): `{invalidates: K2, covers: [K2], expected_covers: [K1-derived set from the listProfilesByPlan read closure]}` — the mismatch between `covers` and the writer-closure of users-table mutations is the INV-002 fact.

**Resulting Finding artifacts (Finding Contract v1.0.0, §2.6 lifecycle/tier semantics):**
1. `TTL-001` on op #2: severity=`major`, confidence=1.0 (`DETERMINISTIC_FACT`), probability=0.7 `[PROVISIONAL context default; EXPERIMENT REQUIRED for calibration]`, impact=`{category:"availability", description:"Cache entries for profile:v1:{tenantId}:{userId} never expire; schema/format migrations or role changes keep serving stale shapes until manual DEL", blast_radius:{units:["getUserProfile","listProfilesByPlan"], keys:["K1"]}}`, lifecycle=`suspected`.
2. `NS-003` on op #3: severity=`major`, confidence=1.0, impact=`{category:"correctness", description:"Invalidation targets profile:{userId} but the writer/readers use profile:v1:{tenantId}:{userId}; updates never invalidate the live key", blast_radius:{keys:["K2"], units:["updateUserPlan"]}}`, `DETERMINISTIC_FACT`, lifecycle=`suspected`.
3. `RACE-004` on `updateUserPlan` (window A): severity=`major`, confidence=1.0, probability=0.4 `[PROVISIONAL; EXPERIMENT REQUIRED to calibrate]`, impact=`{category:"correctness", description:"Concurrent cache-aside repopulation after invalidation can persist a pre-update profile until process restart (no TTL)", blast_radius:{keys:["K1"], units:["getUserProfile"]}}`, `DETERMINISTIC_FACT` (pattern match; probability context-derived).
4. `INV-002` derived: `listProfilesByPlan` serves rows joined from per-user cache keys that the DEL misses → stale plan listings; severity=`major`, `DETERMINISTIC_FACT`.

## 2.13 Versioned Finding Contract (v1.0.0 — the shared interface other sections cite)

`severity`, `confidence`, `probability`, and `impact` are **distinct fields** (FR-16); evidence carries full IR paths; assumptions and missing-evidence declarations are explicit; lifecycle per §2.9; every claim's tier drawn from the six-tier ladder of §1.2 (storage CHECK, §2.4). Deterministic analyzers emit only `DETERMINISTIC_FACT`/`STATIC_INFERENCE`; model-contributed content is capped at `MODEL_HYPOTHESIS`; unresolvable/downgraded items are `UNKNOWN` (§4.1). `[RECOMMENDED]`

```ts
interface FindingContract {  // contract_version: "1.0.0" — bump on any breaking field change
  contract_version: string;
  finding_id: string;          // sha256(rule_id + evidence span + ir_revision)
  rule_id: "INV-002" | "TTL-001" | "NS-003" | "RACE-004";
  severity: "info" | "minor" | "major" | "critical";      // engineering impact class (rule-defined, fixed)
  confidence: number;            // 0..1 — structural certainty the pattern matches (deterministic: 1.0)
  probability: number;           // 0..1 — likelihood the pattern causes a real incident in context
  impact: { category: "correctness" | "availability" | "cost" | "security" | "performance";
            description: string;                       // human statement, no fabricated numbers
            blast_radius: { units: string[]; keys: string[] } };  // derived from key graph, not guessed
  epistemic: "DETERMINISTIC_FACT" | "STATIC_INFERENCE" | "MODEL_HYPOTHESIS" |
             "RUNTIME_OBSERVATION" | "VERIFIED_OUTCOME" | "UNKNOWN";   // FR-8 six-tier ladder (§1.2)
  lifecycle: "suspected" | "supported" | "verified" | "rejected" | "resolved" | "stale";
  evidence: EvidenceBundleRef[];     // spans, op ids, key ids — full trail
  analysis_artifact_cache_key: string | null;   // linkage FK findings→analysis_artifacts
  ir_revision: string; content_hash: string;    // freshness anchors (failure mode 9)
  assumptions: string[]; missing_evidence: string[];
  detected_at: string; revalidated_at: string | null;
}
interface EvidenceBundleRef { bundle_id: string;
  kind: "code_span" | "redis_op" | "key_graph_path" | "model_reasoning" | "doc_quote";
  locator: string; tier: "DETERMINISTIC_FACT" | "STATIC_INFERENCE" | "MODEL_HYPOTHESIS" |
                        "RUNTIME_OBSERVATION" | "VERIFIED_OUTCOME" | "UNKNOWN"; }
```

---

# SECTION 3 — Runtime Design: Investigation Loop, Task Graph, Retrieval

## 3.1 Mermaid diagram (a): investigation state-machine lifecycle (7 states, FR-17)

```mermaid
stateDiagram-v2
    [*] --> QUEUED : question accepted, cost budget reserved
    QUEUED --> PLANNED : objective normalized, evidence requirements computed, task graph built
    PLANNED --> RUNNING : deterministic tasks executing (scheduled by U(t)/(1+est_wall_s))
    RUNNING --> AWAITING_EVIDENCE : retrieval in flight (CTE walks, cache lookups)
    RUNNING --> RUNNING : task done → evaluate stopping rules
    AWAITING_EVIDENCE --> ESCALATED : unmet MODEL_CLAIM requirement → LLM gateway (mode != DETERMINISTIC)
    AWAITING_EVIDENCE --> VALIDATING : deterministic evidence sufficient
    ESCALATED --> VALIDATING : OutputVerifier ran (schema / IrIds / verbatim / tier ceiling)
    VALIDATING --> COMPLETED : report emitted (full or partial)
    RUNNING --> COMPLETED : stopping rule fired (sufficient / diminishing / budget / inaccessible)
    note right of COMPLETED
        COMPLETED[partial] is the bounded outcome on
        budget exhaustion or inaccessible evidence —
        never a silent stop, never an invented conclusion (FR-20)
    end note
```

States: `QUEUED`, `PLANNED`, `RUNNING`, `AWAITING_EVIDENCE`, `ESCALATED`, `VALIDATING`, `COMPLETED` — exactly the seven FR-17 states; the runtime owns request execution without LLM routing of standard tasks. `[RECOMMENDED]`

## 3.2 Mermaid diagram (b): task-graph scheduling and conditional routing

```mermaid
flowchart TD
    P["Planner<br/>(missing-evidence calc)"] --> T1["T1: IR lookup<br/>key closure of pattern X<br/>(deterministic)"]
    P --> T2["T2: analyzer replay on dirty units<br/>(deterministic)"]
    T1 --> T3["T3: MODEL_CLAIM escalation<br/>'is this pub/sub channel consumed?'<br/>(mode != DETERMINISTIC required)"]
    T2 --> T3
    T3 --> G{"OutputVerifier pass?"}
    G -->|"yes"| T5["T5: cost assembly + report"]
    G -->|"no"| R{"stricter retry used?"}
    R -->|"no"| S["One stricter retry: temp=0,<br/>verifier report as correction turn"] --> T3
    R -->|"yes"| D["Downgrade tier → UNKNOWN<br/>task = INCONCLUSIVE<br/>(max 2 provider calls total)"]
    D --> T5
    T1 --> T5
    T2 --> T5
    PQ["Priority queue: dispatch by<br/>U(t) / (1 + est_wall_s) descending<br/>budget gate before each dispatch"] -.->|"orders"| P
```

## 3.3 Mermaid diagram (c): demand-driven retrieval pipeline

```mermaid
flowchart LR
    OBJ["Objective"] --> CK["Cached-knowledge lookup<br/>cache_key = sha256(q + ir_revision + rule_versions)<br/>fresh iff epoch == db_revision_counter snapshot"]
    CK -->|"hit + fresh"| OUT["Annotated answer (tier preserved)"]
    CK -->|"miss"| GEN["Deterministic candidate generation<br/>Q1/Q2/Q3 CTE walks (§2.8) + findings index + FTS5 BM25"]
    GEN --> SCORE["Score & dedup<br/>score(c) = 0.45·bm25 + 0.20·centrality<br/>+ 0.20·recency − 0.15·redundancy"]
    SCORE --> BG{"Fits max_tokens_context?"}
    BG -->|"no"| DROP["Drop lowest-scored WHOLE slices<br/>(never field-truncate a kept slice)<br/>annotate omissions"] --> BG
    BG -->|"yes"| PKG["EvidencePackage (provenance-carrying)"]
    PKG --> ME{"Missing-evidence calc:<br/>unmet MODEL_CLAIM needs?"}
    ME -->|"no"| ASM["Assembled deterministic evidence"]
    ME -->|"yes"| LLM["LLM escalation via §4.1 loop<br/>(redacted package, strict schema)"]
    LLM --> VER["Verifier: re-check claim against cited IrIds"]
    VER --> ASM
    ASM --> CTRL["→ Control loop (§3.5)"]
```

## 3.4 Task-node and retrieval contracts (FR-18; provider-bound fields per §4.2)

```ts
interface TaskNode {
  task_id: string; question_id: string;
  type: "parse" | "ir" | "analyze" | "retrieve" | "reason" | "synthesize";
  objective: string;                       // normalized, imperative, single-deliverable
  inputs: string[];                        // IR ids / file spans / finding ids consumed
  required_evidence: EvidenceRequirement[];
  retrieval_spec: RetrievalQuery;
  depends_on: string[];                    // DAG edges (no cycles; topologically ordered)
  budget: { tokens: number; llm_calls: number; wall_ms: number };
  // budget/retry semantics are OWNED BY the §4.2 provider contract:
  //   token cap = 3,500 (constrained) | 8,500 (advanced) estimated prompt tokens [PROVISIONAL]
  //   retry = (max_transport_retries=2, timeout_ms=30_000); one stricter schema-retry; disabled
  //   provider ⇒ deterministic degradation at scheduling time. Not restated here.
  cache_key: string;                       // composite hash (§2.6) — failure-mode-6 guard
  retry_timeout_policy: { retry_max: number; timeout_ms: number; escalation: EscalationPolicy };
  provenance: ProvenanceEntry[];           // every step incl. provider calls (NFR-6 audit)
  status: "QUEUED" | "PLANNED" | "RUNNING" | "AWAITING_EVIDENCE" | "ESCALATED" | "VALIDATING" | "COMPLETED";
  output_schema: "claim" | "fact_list" | "cost_summary";   // validated post-run
}
interface EscalationPolicy { max_llm_calls: 2; on_failure: "downgrade_tier" | "mark_gap"; }
// escalation_policy tracks §4 semantics: one stricter retry after verifier failure; second
// failure ⇒ claims demoted to UNKNOWN, task INCONCLUSIVE (§4.1 diagram).

type EvidenceRequirement =
  | { kind: "IR_FACT";       tier: "DETERMINISTIC_FACT"; ref: string }   // must cite a key_expr/op/edge id
  | { kind: "FINDING";       tier: "DETERMINISTIC_FACT"; rule: string }  // must cite finding_id, lifecycle in (suspected, supported)
  | { kind: "CODE_SPAN";     tier: "DETERMINISTIC_FACT"; path_glob: string } // resolved to file+span
  | { kind: "MODEL_CLAIM";   tier: "MODEL_HYPOTHESIS";   verify_with: "IR_FACT" | "FINDING" | "CODE_SPAN" }
  | { kind: "DOC_QUOTE";     tier: "STATIC_INFERENCE";   source_allowlist: string[] };  // local/redacted sources only

// Scoring formulas (weights [PROVISIONAL], calibration [EXPERIMENT REQUIRED] via EXP-1/EXP-4):
// Task utility:      U(t) = w_g·E[IG(t)] + w_r·RiskRed(t) − w_c·EstCost(t) − w_s·Slack(t)
//   E[IG(t)]   = Σ_q  P(q unresolved | before t) · P(q resolved | t runs) · I(q)     (I(q) = question weight, uniform 1.0 MVP)
//   RiskRed(t) = Σ_f (f in t.blast_radius) · severity_weight(f.severity)             (critical 3, major 2, minor 1, info 0.25)
//   EstCost(t) = α·est_tokens/1000 + β·est_wall_s + γ·llm_calls·C_call_usd
//   Slack(t)   = max(0, est_wall_s − remaining_budget_s)
// Scheduling priority = U(t) / (1 + est_wall_s)   (value-density; greedy with DAG topological order)
// Retrieval score:  score(c) = 0.45·bm25(q,c) + 0.20·centrality(c) + 0.20·recency(c) − 0.15·redundancy(c)
//   bm25 normalized 0..1; centrality = normalized in-degree over READS/WRITES/KEY_FLOW edges;
//   recency = 1 − min(1, age_days/90); redundancy = max lexical overlap with already-selected slice.

interface RetrievalQuery {
  query_id: string; question_id: string; objective: string;
  kind: "symbol" | "key_pattern" | "metadata" | "graph_traversal";   // §2.8 compilation table
  subject: string; filters: Record<string, string>;
  edge_type_scope: string[];               // edge-type whitelist — conflation guard (failure mode 8)
  kind_filter: string[];                   // node-kind filter (6-column edges shape)
  hops: number;                            // default 3 [PROVISIONAL]; depth cap 4
  k_results: number;                       // default 12 [PROVISIONAL]
  max_tokens_context: number;              // assembly budget (failure-mode-10 floor applies)
  tier_floor: "DETERMINISTIC_FACT" | "STATIC_INFERENCE" | "MODEL_HYPOTHESIS";
  freshness: { ir_revision: string; allow_stale: false };   // failure mode 9
}
```

## 3.5 Complete control-loop pseudocode (FR-32: 80–150 unabstracted lines, all 10 lifecycle steps)

```pseudo
# ControlLoop(question, global_budget, mode) -> InvestigationReport          # mode in {DETERMINISTIC, CONSTRAINED, ADVANCED}

1.  # --- (1) OBJECTIVE NORMALIZATION ---
2.  q_text = strip_politeness(question)
3.  q_text = resolve_pronouns(q_text, prior_turns)                  # "it" → last mentioned key/scope
4.  q_class = classify(q_text)                                      # one of KEY_BEHAVIOR, INVALIDATION_IMPACT,
                                                                    #   CLIENT_PATTERN, COST, GENERAL
5.  q_id = "q-" + sha256(q_text + repo_head_sha)[:12]
6.  budget = {tokens: global_budget.tokens, llm_calls: mode == DETERMINISTIC ? 0 : 2,
              wall_ms: global_budget.wall_ms}
7.  validation_reserve = 0.15 * budget.tokens                        # held back for output validation passes
8.  ledger.open_run(q_id, budget)

9.  # --- (2) CACHED KNOWLEDGE LOOKUP ---
10. cache_key = sha256(q_text || store.db_revision_counter || rule_versions_csv)
11. entry = cache.get(cache_key)
12. if entry is not None and entry.epoch == store.snapshot_epoch():
13.     if hash_chain_verifies(entry.finding_ids, store):            # failure-mode-6 guard: stale anchor ⇒ miss
14.         return annotate_and_close(ledger, entry, "cache_hit")     # tier preserved from entry
15. # miss (or stale anchor) → continue

16. # --- (3) MISSING-EVIDENCE CALCULATION ---
17. requirements = evidence_requirements(q_text, q_class)            # list of EvidenceRequirement
18. satisfied, missing = [], []
19. for req in requirements:
20.     hit = store.lookup(req)                                       # by kind: IR_FACT → id exists at tier;
                                                                    #   FINDING → id in lifecycle (suspected, supported);
                                                                    #   CODE_SPAN → file+span resolves
21.     if hit is not None and hit.tier >= req.tier: satisfied.append((req, hit))
22.     else: missing.append(req)

23. # --- (4) TASK-GRAPH CONSTRUCTION ---
24. tasks = {}
25. for i, req in enumerate(missing):
26.     if req.kind in ("IR_FACT", "FINDING", "CODE_SPAN"):
27.         t = TaskNode(task_id=f"t-{q_id}-{i}", type="retrieve", objective=req_to_objective(req),
28.                      retrieval_spec=compile_query(req), budget={"tokens": 0, "llm_calls": 0, "wall_ms": 2000})
29.     elif req.kind == "MODEL_CLAIM":
30.         assert mode != DETERMINISTIC, "NFR-6 guard: reason task in deterministic mode"   # hard gate
31.         t = TaskNode(task_id=f"t-{q_id}-{i}", type="reason", objective=req_to_objective(req),
32.                      budget={"tokens": 3500 if mode == CONSTRAINED else 8500,
33.                              "llm_calls": 1, "wall_ms": 30000})
34.     tasks[t.task_id] = t
35. for t in tasks.values():                                          # link deps via key-graph reachability
36.     t.depends_on = [u.task_id for u in tasks.values()
37.                     if u.task_id != t.task_id and depends_on_evidence(t, u, store, edge_scope=["CALLS","KEY_FLOW","DATA_FLOW"])]
38. assert not has_cycle(tasks)                                        # DAG invariant

39. # --- (5) TOPOLOGICAL / PRIORITY SCHEDULING ---
40. while incomplete(tasks):
41.     ready = [t for t in tasks.values()
42.              if t.status in ("QUEUED", "PLANNED") and all(tasks[d].status == "COMPLETED" for d in t.depends_on)]
43.     if not ready: break
44.     ready.sort(key=lambda t: -utility_density(t))                  # U(t) / (1 + est_wall_s), §3.4 formulas

45.     # --- (6) BUDGET ENFORCEMENT (before each dispatch) ---
46.     t = ready[0]
47.     projected = estimate_cost(t)                                   # tokens, llm_calls, wall_ms
48.     if ledger.spent + projected.tokens > budget.tokens - validation_reserve:
49.         t.status = "COMPLETED"; t.result = SKIP(reason="budget")   # feeds the partial report
50.         ledger.record_skip(t, projected); continue
51.     if mode == DETERMINISTIC and t.type == "reason":
52.         t.status = "COMPLETED"; t.result = SKIP(reason="deterministic_mode")               # never a provider call
53.         continue

54.     # --- (7) DETERMINISTIC EXECUTION ---
55.     if t.type in ("retrieve", "analyze"):
56.         t.status = "RUNNING"; t0 = now()
57.         if t.type == "retrieve":
58.             rows = store.run_compiled_query(t.retrieval_spec)       # Q1/Q2/Q3 per §2.8, snapshot read
59.             slices = assemble_slices(rows, k=12, max_tokens=1500)   # whole-slice drop policy, §3.3
60.         else:
61.             slices = analyzer_engine.replay(dirty_units_only=True)  # §2.11 step 5
62.         t.result = slices; t.status = "AWAITING_EVIDENCE"
63.         ledger.record(t, wall_ms=now() - t0, tokens=0, llm_calls=0)

64.     # --- (8) CONDITIONAL LLM ESCALATION (MODEL_CLAIM nodes only) ---
65.     elif t.type == "reason":
66.         t.status = "ESCALATED"; t0 = now()
67.         evidence = build_evidence_package(t.retrieval_spec, tier_floor=t.required_evidence[0].tier)
68.         prompt = PromptBuilder.build(evidence)                      # OPAQUE: sanitization + redaction + assembly
                                                                    #   owned by §4 (EgressGate is the sole choke point)
69.         result = LLMGateway.call(prompt, task_schema=t.output_schema)   # §4.2 contract governs retries/fallback
70.         report = OutputVerifier.verify(result, evidence, store)     # 4 checks: schema_valid, irids_exist,
                                                                    #   literals_verbatim, tier_ceiling
71.         if report.passed:
72.             t.result = demote_none(result.claims, ceiling="MODEL_HYPOTHESIS")   # verified model claims
73.         elif not t.escalated_strict_once:
74.             t.escalated_strict_once = True                          # one stricter retry (temp=0,
75.             t.retry_context = report                                #   verifier report as correction turn)
76.             continue                                                # re-dispatch under same budget gate
77.         else:
78.             t.result = UNKNOWN(gaps=report.demoted_to_unknown)      # no quiet tier upgrade (FR-8)
79.             t.status_note = "INCONCLUSIVE"
80.         ledger.record(t, wall_ms=now() - t0, tokens=result.usage.prompt_tokens + result.usage.output_tokens,
                       llm_calls=1)
81.         t.status = "VALIDATING"

82.     # --- (9) OUTPUT VALIDATION (per completed task, then whole report) ---
83.     for claim in flatten(t.result):
84.         refs = [r for r in claim.evidence if r.tier >= claim.tier]   # every claim cites >= 1 ref at/above its tier
85.         if not refs:
86.             claim.tier = "UNKNOWN"; claim.note = "uncited claim demoted"
87.         fr7_lint(claim)                                             # reject fabricated timing numbers, invented API
                                                                    #   names, cross-analyzer claims without provenance
88.     # --- (10) STOPPING EVALUATION (after each task completion) ---
89.     if all(r in satisfied_ids for r in requirement_ids(requirements)):
90.         stop_reason = "sufficient_evidence"; break
91.     if len(gain_history) >= 3 and max(gain_history[-3:]) < EPSILON:  # EPSILON = 0.05 [PROVISIONAL]
92.         stop_reason = "diminishing_gain"; break
93.     if ledger.spent >= budget.tokens or now() - run_start > budget.wall_ms:
94.         stop_reason = "budget_exhausted"; break
95.     if all(req in inaccessible for req in missing):                  # unresolvable deps marked UNAVAILABLE
96.         stop_reason = "inaccessible_evidence"; break

97. # --- report assembly ---
98. gaps = [r for r in requirements if r not in satisfied_ids and r not in resolved_ids]
99. report = InvestigationReport(
100.    claims=tiered_claims, findings=store.findings(referenced_by=claims),
101.    unanswered=[(r, skip_reason, projected_cost) for r in gaps],      # bounded partial report (FR-20)
102.    cost=ledger.close_run(),
103.    stop_reason=stop_reason or "sufficient_evidence")
104. cache.put(cache_key, report, epoch=store.db_revision_counter,
              anchors=[f.id for f in report.findings])                  # hash-anchored cache write
105. return report
```

Line count: 125 lines (verified on disk), within the 80–150 mandate, covering all ten mandated lifecycle steps (objective normalization L1–8; cached knowledge lookup L9–15; missing-evidence calculation L16–22; task-graph construction L23–38; topological/priority scheduling L39–44; budget enforcement L45–53; deterministic execution L54–63; conditional LLM escalation L64–81; output validation L82–87; stopping evaluation L88–96 + report assembly L97–125). `[RECOMMENDED]` (structure); numeric constants `[PROVISIONAL]`.

## 3.6 Evidence-aware stopping rules (FR-20, hard rules)

1. **Sufficient evidence** — every EvidenceRequirement satisfied at its required tier → complete report.
2. **Diminishing marginal information gain** — after each completed task, recompute remaining uncertainty; if the last 3 completed tasks each contributed < ε = 0.05 relative gain `[PROVISIONAL; EXP-4 calibrates]`, stop; annotate which gaps remain.
3. **Budget exhaustion → bounded partial report** — the report emits satisfied evidence plus an explicit "NOT ANSWERED (budget)" list with the task ids skipped and their projected costs; no fabricated completion.
4. **Inaccessible evidence** — a dependency is unresolvable (no writer for a key, symbol unresolved, file unreadable, no trace data) → mark that requirement UNAVAILABLE, downgrade dependent MODEL_CLAIMs to UNKNOWN or omit them with annotation; never guess silently.

## 3.7 Section 3 decisions and shared-interface notes

Contracts (TaskNode, EvidenceRequirement, RetrievalQuery, 7-state machine): `[RECOMMENDED]`. Scoring weights, ε = 0.05, k_results = 12, hops = 3, max_llm_calls = 2, 15% validation reserve, budget caps (≤3,500 / ≤8,500 est. prompt tokens): `[PROVISIONAL]`, calibration `[EXPERIMENT REQUIRED]` (EXP-1, EXP-4). TaskNode budget/retry fields and the `mode != DETERMINISTIC` guard are bound to the §4.2 provider contract — single source of truth is Section 4; if §4 retry/fallback semantics change, `EscalationPolicy` follows. The walkthrough snippet (§2.12) doubles as the QA suite's first golden fixture.

---

# SECTION 4 — Model Isolation, Token Efficiency, Security and Governance

## 4.1 Mermaid diagram (a): constrained model reasoning + deterministic verification loop

This is the canonical escalation path; the control loop (§3.5) invokes it only for `type="reason"` tasks in Constrained/Advanced modes. `[RECOMMENDED]`

```mermaid
flowchart TD
    GAP["Evidence gap in TEG<br/>(ambiguous wrapper, unresolved interpolation)"] --> MODE{"Operating mode?"}
    MODE -->|"deterministic (NFR-6)"| UNK0["Emit UNKNOWN gap<br/>zero provider calls — never a provider call"]
    MODE -->|"constrained / advanced"| ESC["C-4 creates reason task<br/>TaskNode: token_budget, retry_policy, tier_ceiling=MODEL_HYPOTHESIS"]
    ESC --> SAN["Sanitize extracted snippet text<br/>stage 1: control/bidi chars → stage 2: injection patterns<br/>→ stage 3: JSON escaping → stage 4: budget truncation (§4.8)"]
    SAN --> RED["Redact secrets / Redis URIs<br/>classes S1–S4, BEFORE prompt assembly (§4.9)"]
    RED --> PKG["EvidencePackage assembled<br/>context budget capped per mode (§4.4)"]
    PKG --> PB["PromptBuilder.build()<br/>stable prefix → task schema → evidence last (§4.6 mech-9)"]
    PB --> EST{"est. tokens ≤ task token_budget?"}
    EST -->|"no"| DROP["drop lowest-ranked evidence slice → re-estimate"]
    DROP --> EST
    EST -->|"yes"| EG["EgressGate.redact(PromptPlan)<br/>SOLE egress choke point — idempotent second pass (§4.9)"]
    EG --> CALL["Provider call — schema-strict<br/>(OpenAI text.format json_schema strict / Anthropic strict tool use, §4.3)"]
    CALL -->|"transport failure after retry_policy"| DEG["Deterministic degradation:<br/>answer from IR evidence only + explicit UNKNOWN gaps<br/>task = PARTIAL/INCONCLUSIVE — never invented content (FR-20)"]
    CALL --> OV["OutputVerifier.verify() — deterministic checks"]
    OV --> CHK1{"schema-valid?"}
    CHK1 -->|"no"| DEM
    OV --> CHK2{"cited IrIds exist in IR?"}
    CHK2 -->|"no"| DEM["Demote unverifiable claims → UNKNOWN"]
    OV --> CHK3{"quoted literals substring-verbatim<br/>in evidence?"}
    CHK3 -->|"no"| DEM
    OV --> CHK4{"no claim above tier ceiling<br/>(MODEL_HYPOTHESIS max)?"}
    CHK4 -->|"no"| DEM
    CHK1 -->|"all pass"| STORE["Store as MODEL_HYPOTHESIS<br/>+ provider + verification-report provenance"]
    DEM --> RETRY{"stricter retry used<br/>this task?"}
    RETRY -->|"no"| STRICT["One stricter retry: temp=0,<br/>verifier failure report appended as user turn,<br/>budget-checked"]
    STRICT --> OV
    RETRY -->|"yes"| INC["Task = INCONCLUSIVE<br/>claims remain UNKNOWN — no quiet tier upgrade (FR-8)"]
    STORE --> AUD["Egress audit entry appended (§4.11)<br/>provenance ledger updated (NFR-6)"]
    INC --> AUD
    DEG --> AUD
```

Spec notes: (1) the MODE guard is enforced by construction in the control loop — a task with `type="reason"` requires `mode != DETERMINISTIC` (NFR-6); (2) every verifier check is a pure deterministic function over (ProviderResult, EvidencePackage, IR snapshot) — no LLM judges the LLM; (3) the tier ceiling is `MODEL_HYPOTHESIS` in both constrained and advanced modes; `VERIFIED_OUTCOME` is reachable only via `RUNTIME_OBSERVATION` or the human `learn` gate (§4.13).

## 4.2 Reasoning provider interface contract (code-level; single source of truth for TaskNode budget/retry fields)

All types are in-process Python dataclasses; the only machine boundary is runtime→cloud LLM. `[RECOMMENDED]`

```python
@dataclass(frozen=True)
class UsageFields:
    prompt_tokens: int
    cached_tokens: (
        int | None
    )  # OpenAI: prompt_tokens_details.cached_tokens (round-2 verified)
    cache_read_tokens: int | None  # Anthropic: cache_read_input_tokens
    cache_write_tokens: (
        int | None
    )  # Anthropic: cache_creation_input_tokens (write = 1.25×/2× base)
    output_tokens: int
    bytes_sent: int  # serialized request body size, measured pre-send


@dataclass(frozen=True)
class ProviderCaps:
    provider_id: str  # "openai" | "anthropic" | ...
    model_id: str
    structured_output: Literal[
        "json_schema_strict", "json_mode", "tool_input_schema_strict", "none"
    ]
    prompt_caching: Literal["automatic", "explicit_breakpoints", "none"]
    max_cache_breakpoints: int | None  # Anthropic ≤ 4; OpenAI: None (automatic)
    min_cacheable_prefix_tokens: int  # OpenAI ≥ 1,024; Anthropic per-model: 1,024 (Sonnet) / 4,096 (Opus, Haiku 4.5)
    context_window_tokens: int
    max_output_tokens: int
    model_class: Literal["weaker", "stronger"]  # drives routing policy (§4.5.4)


@dataclass(frozen=True)
class Snippet:  # the ONLY snippet type PromptBuilder accepts
    content: str  # already sanitized (§4.8) AND redacted (§4.9)
    path: str  # repo-relative
    span: tuple[int, int]  # 1-based start..end lines
    sha256: str  # hash of sanitized content (audit + dedup)
    truncation_markers: tuple[int, ...]  # line offsets where budget truncation cut


@dataclass(frozen=True)
class EvidencePackage:
    schema_version: str
    task_id: str
    mode: Literal["constrained", "advanced"]
    task_kind: str  # "classify_wrapper" | "resolve_interpolation" | "hypothesize_remediation" | ...
    stable_prefix_id: str  # id into the static prompt-template table (§4.6 mech-8)
    snippets: tuple[Snippet, ...]
    ir_claims: tuple[str, ...]  # cited IR row ids only — never raw IR dumps
    tier_ceiling: Literal["MODEL_HYPOTHESIS"]
    token_budget: int  # per-task cap, copied from TaskNode.budget.tokens


@dataclass(frozen=True)
class ConstrainedTask:
    schema_version: str
    task_id: str
    task_kind: Literal[
        "classify_wrapper", "resolve_interpolation", "infer_key_template"
    ]
    evidence: EvidencePackage
    output_schema: Mapping[str, Any]  # strict JSON schema, versioned per task_kind
    tier_ceiling: Literal["MODEL_HYPOTHESIS"]
    token_budget: int
    retry_policy: tuple[int, int]  # (max_transport_retries=2, timeout_ms=30_000)


@dataclass(frozen=True)
class AdvancedTask:
    schema_version: str
    task_id: str
    task_kind: Literal["hypothesize_remediation", "tradeoff_synthesis"]
    evidence: EvidencePackage
    output_schema: Mapping[
        str, Any
    ]  # hypotheses[] each: {claim, cited_ir_ids, quoted_literals, tier}
    tier_ceiling: Literal[
        "MODEL_HYPOTHESIS"
    ]  # advanced NEVER emits above hypothesis tier
    token_budget: int
    retry_policy: tuple[int, int]
    hypothesis_slots: int  # ≤ 5 hypotheses per call — bounds output tokens


@dataclass(frozen=True)
class ProviderResult:
    raw: str
    parsed: Any | None
    schema_valid: bool
    usage: UsageFields
    latency_ms: int
    failed: bool
    failure_reason: Literal[
        "transport", "timeout", "rate_limit", "schema_parse", "refusal", None
    ]


@dataclass(frozen=True)
class VerificationReport:
    checks: tuple[
        tuple[str, bool], ...
    ]  # ("schema_valid", True), ("irids_exist", ...),
    # ("literals_verbatim", ...), ("tier_ceiling", ...)
    passed: bool
    demoted_to_unknown: tuple[str, ...]  # claim ids demoted, with failing-check id
```

Structured-output resolution: providers weaker than `json_schema_strict` are handled as — strict schema preferred; `json_mode` is the declared fallback; `none` ⇒ provider rejected for reason tasks (deterministic post-parse alone is not trusted to bound output for tiered storage). `[RECOMMENDED]`

## 4.3 Provider contract constants (round-2 research, primary-source verified)

These constants bind the §4.2 contract and the §4.6 mech-9 layout: `[RECOMMENDED]` (facts); their exploitation thresholds `[PROVISIONAL]`.

| Constant | OpenAI | Anthropic |
|---|---|---|
| Prompt-caching mode | Automatic (no integration changes); optional manual `prompt_cache_breakpoint` object | Top-level `cache_control` (automatic) or ≤ 4 explicit `cache_control` breakpoints |
| Minimum cacheable prefix | 1,024 tokens; increments in 128-token steps | Per-model: 1,024 tokens (Sonnet); 4,096 tokens (Opus, Haiku 4.5) |
| Cached-usage field | `prompt_tokens_details.cached_tokens` | `cache_read_input_tokens` (reads); `cache_creation_input_tokens` (writes, billed 1.25× base input; 2× for 1-hour TTL) |
| Structured outputs | `strict: true` inside `tools[].function` OR `response_format`/`text.format` with `type: "json_schema"` | Tool use with `input_schema` (JSON Schema on tool parameters) |

Implications: (i) the stable-prefix layout must respect OpenAI's 1,024-token/128-increment model *and* Anthropic's per-model minima and ≤4-breakpoint limit; (ii) token accounting normalizes `cached_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens` into the canonical `UsageFields` (§4.2); (iii) structured-output adapters implement both `strict:true`+json_schema (OpenAI) and tool-use `input_schema` (Anthropic) with JSON-mode fallback.

## 4.4 Context budget caps per mode (shared TaskNode defaults)

`[PROVISIONAL — tuned by the Section-5 ablation; shared with §3.4/§3.5, never tuned independently]`

| Cap | Constrained | Advanced | Rationale |
|---|---|---|---|
| total evidence tokens | ≤ 2,000 | ≤ 6,000 | classification needs a window, not a file; multi-hypothesis needs cross-scope slices |
| max snippets | 6 | 12 | |
| max lines per snippet | 40 | 80 | |
| max IR claims cited | 10 | 30 | |
| instruction (variable tail) tokens | ≤ 300 | ≤ 600 | |
| est. total prompt tokens | ≤ 3,500 | ≤ 8,500 | leaves ≥1,024-token stable prefix for OpenAI automatic caching (§4.3) |

Caps are enforced by the PromptBuilder estimator; violation ⇒ lowest-ranked evidence dropped (ranking: proximity to the Redis callsite, then IR-claim centrality), then the task is skipped with a budget-exhaustion stop reason (FR-20).

## 4.5 Retry, fallback and degradation behaviour

1. **Transport failure** (network/timeout/rate-limit): retry up to `retry_policy[0]` with exponential backoff (1 s, 4 s); on exhaustion → **deterministic degradation**: the answer is composed strictly from IR evidence already gathered, unresolvable parts rendered as `UNKNOWN`, task = `PARTIAL` or `INCONCLUSIVE` (FR-20 — bounded partial report, never invented conclusions). `[RECOMMENDED]`
2. **Schema-parse failure** or **verifier rejection**: exactly **one stricter retry** — temperature 0, the verifier failure report appended as a user-turn correction, token budget re-checked. Second failure → demote every unverifiable claim to `UNKNOWN`, task = `INCONCLUSIVE` (§4.1 path). `[RECOMMENDED]`
3. **Provider disabled** (config `provider.enabled=false`, or no key): Constrained/Advanced tasks are never silently attempted — the control loop routes them to deterministic degradation at scheduling time; `doctor` reports the posture. Deterministic Mode is **always available**. `[RECOMMENDED]`
4. **Weaker-vs-stronger routing policy** `[PROVISIONAL]`: Constrained `classify_wrapper`/`infer_key_template` tasks → `model_class="weaker"`; `resolve_interpolation` and all Advanced tasks → `model_class="stronger"`. Escalation: if a weaker-model result fails verification twice, one re-attempt on the stronger class is permitted **within the task's token budget**, then INCONCLUSIVE. The routing decision is recorded in `TaskNode.provenance` and the egress audit entry.

**Per-task token budget enforcement:** `TaskNode.budget.tokens` is the hard cap. PromptBuilder estimates prompt tokens (chars ÷ 4 heuristic; provider tokenizer when available) before send; post-call `usage` actuals are written to `TaskNode.provenance` and the egress audit log. A task that would exceed budget is never sent partially trimmed beyond the evidence-drop policy — budget exhaustion is a visible stop reason, never a truncated silent send.

## 4.6 Token-efficiency mechanisms table (FR-25, 10 mechanisms)

Each mechanism maps to one Section-5 ablation; the "savings isolation" column names the metric and the audit/provenance field that records the saving. `[RECOMMENDED]`

| # | Mechanism | Baseline failure mode | Exact runtime mechanism | Correctness risk | Local compute overhead | Savings isolation (metric + field) |
|---|---|---|---|---|---|---|
| 1 | Deterministic offloading | LLM invoked for questions IR traversal answers → cost + hallucination risk | Control loop schedules deterministic tasks first; `type="reason"` only for evidence gaps the planner proves the IR cannot close | Mis-scoping: something deterministic marked as reasoning → false certainty; mitigated by tier ceilings + verifier | None (negative — saves compute) | `provider_calls_per_query`, `tokens_saved_vs_llm_baseline` on synthetic replay; fields: `TaskNode.provenance` (absence of provider entries) + audit `task_kind` distribution |
| 2 | Artifact reuse | Same wrapper/template re-analyzed and re-sent every query | Evidence packages cite content-addressed IR ids + snippet `sha256`; verified MODEL_HYPOTHESIS results reused via the composite cache key (§2.6) | Stale reuse after rule/IR change — invalidated by composite-key versions | Hash lookups O(1) | `task_cache_hit_rate`, `tokens_avoided_per_hit`; fields: audit `cache_key`, provenance `teg_cache_hit` |
| 3 | Compact snippet/IR slicing | Whole-file (or multi-file) dumps in every prompt | Windowed extraction: ≤40-line slices around Redis callsites; IR claims cited as typed ids | Truncation loses the binding line — truncation markers recorded; ranked windows by callsite proximity | Window extraction O(ops) per file | `avg_evidence_bytes_per_call` vs full-file baseline; fields: audit `prompt_bytes`, `snippet_count` |
| 4 | Call deduplication | Identical ambiguous callsite classified N times (once per occurrence) | Canonical dedup key = `(task_kind, evidence content hash)`; one provider call, result fanned out to all citing sites | Wrong generalization: sites deduped that differ materially — dedup only on identical evidence hash, per-site IR ids re-verified | sha256 over evidence | `dedup_ratio` (calls saved ÷ candidate calls); field: provenance `dedup_source_task_id` |
| 5 | Incremental diffs | Whole-repo context re-sent and re-reasoned each run | git-diff invalidation (§2.11): only changed-file slices enter evidence packages | Missing cross-file edge to an unchanged file — covered by dependency-DAG propagation | diff computation O(changed files) | `delta_bytes ÷ full_bytes` per run pair; field: audit `prompt_bytes` trend across revisions |
| 6 | Strict per-task token budgets | Context creep: each call a bit larger until cost explodes | `TaskNode.budget.tokens` enforced by estimator pre-send (§4.5); evidence-drop policy ranked | Evidence starvation → INCONCLUSIVE (correct by design: bounded partial, FR-20) | Token-estimation pass | `budget_exhaustion_rate`, `tokens_per_task` p50/p95; fields: audit `budget_declared`/`budget_used` |
| 7 | Early stopping | Analysis continues after information saturates | Evidence-aware stopping (§3.6): sufficient evidence / diminishing gain / budget exhaustion / inaccessible evidence | Premature stop on diminishing-gain threshold — ε tuned in its ablation; wrong-side stop recorded as stop_reason | Gain estimation per scheduling round | `tokens_per_completed_finding`; field: provenance `stop_reason` |
| 8 | Zero giant system prompts | Kitchen-sink system prompt re-billed at full price every call | Per-`task_kind` minimal instruction templates (≤300-token variable tail, §4.4); shared stable-prefix table | Guardrails missing from short prompt — compensated because OutputVerifier is deterministic, not prompt-compliance-based | None | `system_prompt_token_share`; field: audit `prompt_section_breakdown` |
| 9 | Provider prompt caching | Identical prefixes reprocessed at full input price each call | Stable-prefix layout: constants → task schema → evidence last (§4.3 constants); OpenAI automatic ≥1,024 tokens/128-token increments; Anthropic ≤4 `cache_control` breakpoints, per-model minima 1,024/4,096 | Provider-side retention of (redacted) prompt content — safe by construction because redaction precedes assembly (§4.9); Anthropic write=1.25×/read-below-base accounted | Layout discipline only | `cached_token_ratio = cached ÷ prompt_tokens`; fields: audit `usage.cached_tokens` / `cache_read_tokens` / `cache_write_tokens` |
| 10 | Strict structured outputs | Free-text output → JSON-repair re-prompts; each parse retry costs output + re-input tokens | OpenAI `text.format {type:"json_schema", strict:true}` / Anthropic strict tool-use `input_schema` grammar-constrained sampling; `json_mode` fallback → deterministic post-parse; `none` → provider rejected for reason tasks | Over-rigid schema truncates valid claims — schemas are versioned per task_kind and evolve only via the human-gated loop (§4.13) | Schema-definition maintenance (authoring-time, zero runtime) | `parse_retry_count` (target ≈ 0), `output_tokens_per_task`; fields: audit `schema_valid`, `parse_retry_count` |

## 4.7 The three operating modes (FR-24, exact boundaries)

| Mode | Boundary | Output guarantee |
|---|---|---|
| **1. Deterministic Mode** | Zero LLM calls (hard-enforced, §4.12); every task is parse/ir/analyze/retrieve/synthesize | Proven facts (`DETERMINISTIC_FACT`/`STATIC_INFERENCE`), explicit `UNKNOWN` gaps; any question needing a model is answered with a typed gap, not a guess |
| **2. Constrained Reasoning Mode** | Narrowly scoped tasks only (`classify_wrapper`, `resolve_interpolation`, `infer_key_template`); strict JSON output schemas; compact evidence packages (≤3,500 est. prompt tokens); post-call deterministic verification | Model output capped at `MODEL_HYPOTHESIS`; unverifiable parts → `UNKNOWN`; per-call budget-bounded |
| **3. Advanced Reasoning Mode** | Multi-hypothesis trade-off synthesis and remediation evaluation (≤5 hypotheses/call); still bound by strict source-provenance checks; ≤8,500 est. prompt tokens | Same tier ceiling; every hypothesis carries cited IR ids + verbatim-quoted literals, verifier-enforced |

## 4.8 Prompt-injection sanitization pipeline (on extracted snippet text)

Applied at extraction time, in this fixed order, before any string can become part of an EvidencePackage. `[RECOMMENDED]`

1. **Stage 1 — control/bidi character stripping**: remove all C0 control chars except `\n`/`\t`, DEL, C1 range; remove zero-width chars (U+200B–U+200F), bidi overrides/embeddings (U+202A–U+202E, U+2066–U+2069), line/paragraph separators U+2028/2029, BOM. Rationale: bidi spoofing and zero-width homoglyph smuggling defeat both human review and pattern matching.
2. **Stage 2 — injection-pattern detection** (NFKC-normalize text first for match stability). Exact pattern classes, each with class id:
   - `INJ-01 instruction-override`: `/(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)/i`
   - `INJ-02 role hijack`: `/(you\s+are\s+now|from\s+now\s+on|act\s+as|pretend\s+to\s+be|new\s+instructions?)\b/i`
   - `INJ-03 system-prompt probing`: `/(system\s*prompt|repeat|print|reveal)\s+.{0,20}(instructions?|prompt|rules?)/i`
   - `INJ-04 tool/action bait`: `/(call|invoke|execute|run)\s+(the\s+)?(tool|function|api|command|shell)/i`
   - `INJ-05 format override`: `/(respond|reply|answer|output)\s+(only\s+)?(in|with)\s+(plain\s+text|english|no\s+json|without\s+json)/i`
   - `INJ-06 fence escape`: any occurrence of three or more backticks inside snippet content (would terminate the evidence block)

   Handling: matched spans are **replaced**, not deleted, with the literal marker `[SANITIZED:<class_id>]` — provenance preserved, replacement counted per class. `INJ-06` additionally triggers JSON escaping of the whole snippet (stage 3), making the pattern structurally impossible in the final prompt.
3. **Stage 3 — escaping**: snippet text is embedded into the prompt **JSON-encoded** (`json.dumps`), so backticks, newlines and quotes cannot break out of the evidence block; the task instruction states that evidence content is untrusted data, never directives.
4. **Stage 4 — budget truncation**: snippets truncated to the per-mode line cap with truncation markers recorded in `Snippet.truncation_markers`; cuts placed at line boundaries (never mid-identifier), lowest-relevance content dropped first.

Failure posture: sanitization is all-or-nothing per snippet — an internal error marks the snippet unusable (a `Snippet` cannot be constructed) rather than passing unsanitized text forward; the §4.2 type discipline makes an unsanitized path to a prompt unrepresentable.

## 4.9 Secret / Redis-URI redaction rules

Ordered deterministic pipeline; every replacement increments a per-class counter for the audit log. `[RECOMMENDED]` (S3 thresholds `[EXPERIMENT REQUIRED]`)

| Class | Rule (regex / heuristic) | Replacement format |
|---|---|---|
| `S1` Redis URI credentials | `redis[s]?://[^\s:@/]+:[^\s@/]+@` (userinfo form) and `?password=` query params | `redis[s]://<REDACTED:S1-<hash8>>@<REDACTED-host>:<port>/<db>` — credentials and hostname masked; port/db shape kept for engineering value |
| `S2` config/env secret literals | `(REDIS_URL|REDIS_PASSWORD|REDIS_AUTH|PASSWORD|SECRET|TOKEN|API_KEY|AUTH)\s*[=:]\s*["']?<value>` (non-greedy to delimiter) | `<REDACTED:S2-<hash8>>` |
| `S3` high-entropy string literals | quoted strings ≥ 20 chars, no whitespace, Shannon entropy ≥ 3.5 bits/char, alphabet ⊆ base64/hex/urlsafe (thresholds tuned on the corpus to bound false-positive rate; initial gate published with EXP-4 results) | `<REDACTED:S3-<hash8>>` |
| `S4` known secret formats | AWS `AKIA[0-9A-Z]{16}`; GitHub `gh[pousr]_[A-Za-z0-9]{36,255}`; Slack `xox[baprs]-`; Anthropic `sk-ant-`; OpenAI `sk-(proj-)?[A-Za-z0-9_-]{20,}`; JWT `eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.`; PEM `-----BEGIN [A-Z ]*PRIVATE KEY-----…-----END` | `<REDACTED:S4-<hash8>>` |

`<hash8>` = first 8 hex chars of sha256(original) — identical secrets collapse to identical placeholders (preserves "same credential reused here" semantics) without leaking content. Redaction is **idempotent**: `redact(redact(x)) == redact(x)` — placeholders never re-match.

**Ordering guarantee (redact before assembly) — enforced structurally, not by convention:**
1. `RawSnippet` (raw repo text) is only constructible inside C-1/C-2 extraction;
2. the sole path `RawSnippet → sanitize() → redact() → Snippet` lives in C-7; `Snippet` is the only type `PromptBuilder` accepts;
3. `EgressGate.redact(PromptPlan)` is the **single egress choke point** — the provider transport adapter refuses any request body not produced through it (the transport layer asserts a gate-issued request token);
4. the gate re-runs the full redaction pass over the assembled plan as a second defense: expected delta = **zero new replacements**; a non-zero delta means an ordering violation upstream and fails the call, logging `ordering_violation=true` (tested by EXP-4);
5. provider prompt caches retain only post-redaction content — compatible with the sanctioned cloud-egress posture (a cached prefix cannot be un-cached; the pipeline guarantees nothing unredacted ever enters one).

## 4.10 Read-only sandboxing posture for the target repo

`[RECOMMENDED]` core / `[PROVISIONAL]` hard mode:

- All repo file access opens `O_RDONLY`; the runtime's only writes go to its own cache/audit dir (`--cache-dir`, default under the user cache home — never inside the target repo).
- `git` invoked read-only only (`diff`, `log`, `rev-parse` with `-C <repo>`); no checkout/commit/clean ever issued; source patching out of scope (§2.9).
- Any subprocess (e.g. a future ts-morph bridge) runs with cwd = scratch dir, not the repo.
- **Verification**: `doctor --security` hashes a deterministic sample of repo files before/after a run and asserts zero modifications; a hash mismatch is a hard failure.
- **Hard mode** `[PROVISIONAL]`: optional OS sandbox enforcement — macOS `sandbox-exec` profile (read-only file-glyph on repo path) / Linux `bubblewrap --ro-bind` or Landlock — opt-in flag; MVP ships code-discipline + doctor verification as the default posture.

## 4.11 Resource-exhaustion caps

`[RECOMMENDED]` (numeric defaults provisional)

| Cap | Value | Exceeded ⇒ |
|---|---|---|
| max file size parsed | 1 MB | file skipped, recorded as explicit UNKNOWN gap (FR-10) |
| AST node budget per file | 500,000 tree-sitter nodes | truncation → `ParseResult.unresolved`, no silent drop |
| flow-analysis recursion depth | 50 frames | deeper path → UNKNOWN node |
| per-task token budget | from TaskNode (defaults §4.4) | evidence drop → skip → budget-exhaustion stop reason |
| per-run token ceiling | 100,000 tokens (config) | remaining task-graph tasks unrun; bounded partial report (FR-20) |
| analyzer timeout | 5 s per file-batch, 60 s per analyzer run | analyzer marked failed in provenance; findings omitted with gap declaration |
| snippet count / lines | 6×40 constrained, 12×80 advanced | lowest-ranked evidence dropped |
| deterministic query time | 2 s soft target (NFR-3) | query returns partial with timing warning |

## 4.12 Deterministic-mode zero-LLM guarantee (NFR-6)

Enforcement stack: (1) the control loop refuses `type="reason"` tasks when `mode=DETERMINISTIC` (state-machine guard, §4.1 branch); (2) the provider transport requires a mode token issued by the control loop — no token, no send; (3) every run appends a provenance ledger entry; a run with `mode=DETERMINISTIC` and ≥1 provider provenance entry fails a post-run integrity check and surfaces in `doctor`. Verified in the benchmark protocol as a zero-call demonstration. `[RECOMMENDED]`

## 4.13 Egress audit log schema (NFR-5 samplable) and the human-gated learning loop

One JSONL record per provider call at the egress audit file under the runtime's cache/audit dir — default `~/.cache/redis-intel/audit/egress.jsonl` (overridable via `--cache-dir`; never inside the target repo). **The log never contains prompt text or snippet content — hashes only** (secrets must not leak via the audit channel itself). `[RECOMMENDED]`

```json
{
  "ts": "2026-10-20T22:41:07Z",
  "run_id": "r-9f31", "task_id": "t-17",
  "mode": "constrained", "task_kind": "classify_wrapper",
  "provider": "openai", "model": "...", "model_class": "weaker",
  "prompt_sha256": "...", "prompt_bytes": 4127,
  "prompt_section_breakdown": {"stable_prefix": 1100, "task_schema": 180, "evidence": 2120, "instruction": 240},
  "budget_declared": 3500, "budget_used": 3640,
  "redaction_counts": {"S1": 2, "S2": 1, "S3": 0, "S4": 0},
  "sanitization_counts": {"INJ-06": 1},
  "ordering_violation": false,
  "evidence_sha256": ["...", "..."], "evidence_ir_ids": ["OP-123", "KEY-45"],
  "cache_key": "sha256(...)",
  "usage": {"prompt_tokens": 1180, "cached_tokens": 1024, "cache_read_tokens": null,
            "cache_write_tokens": null, "output_tokens": 210, "bytes_sent": 4127},
  "parse_retry_count": 0, "schema_valid": true,
  "verification": {"passed": true, "checks": {"schema_valid": true, "irids_exist": true,
                  "literals_verbatim": true, "tier_ceiling": true}},
  "result_tier": "MODEL_HYPOTHESIS"
}
```

NFR-5 sampling: any auditor greps sampled `prompt_sha256`-correlated captures (EXP-4) and the redaction counters; zero unredacted matches is checkable without access to the live prompt.

**Mermaid diagram (b): human-gated offline learning / regression workflow (FR-29)**

```mermaid
flowchart LR
    subgraph RUNTIME["Runtime (no self-modification path)"]
        FB["feedback capture:<br/>developer rejections, confirmed false positives,<br/>parser failures → feedback table (dev-split only)"]
    end
    OBS["1 Observe<br/>triage inbox: FP reports, rejections,<br/>parser failures, egress-audit anomalies"] --> DIAG["2 Diagnose<br/>reproduce as fixture; root-cause class:<br/>analyzer bug · threshold · parser gap · redaction FP"]
    DIAG --> PROP["3 Propose<br/>engineer edits rule/threshold/parser/<br/>redaction pattern — NEVER the holdout"]
    PROP --> EVAL["4 Evaluate<br/>regression fixtures + dev split,<br/>then LOCKED holdout corpus gate:<br/>precision/recall delta vs previous rule version"]
    EVAL --> GATE{"5 Approve<br/>HUMAN gate — differential report review"}
    GATE -->|"reject"| DIAG
    GATE -->|"approve"| REC["6 Record<br/>bump rule version; commit fixtures to dev split;<br/>holdout content hashes untouched; release note"]
    REC --> MEAS["7 Measure<br/>holdout precision/recall + FP rate published;<br/>drift feeds Observe again"]
    MEAS --> OBS
    FB -.->|"feeds Observe; never writes rules,<br/>tiers, or holdout autonomously"| OBS
```

Governance notes: (i) the runtime never transitions its own rules, thresholds, redaction patterns, or epistemic tiers from model or feedback data — every transition crosses the human `Approve` gate (FR-29); (ii) `learn` is an interactive offline CLI subcommand, not an autonomous loop; (iii) tier upgrades happen only here or via re-derivation; (iv) regression fixtures: confirmed false positives, developer rejections, and parser failures are each captured as a fixture triple `(input slice, expected finding set, root-cause class)` committed to the dev split — parser failures additionally produce an `UnresolvedNode` fixture so FR-10 behaviour is regression-tested; (v) **locked holdout corpus**: a fixed, content-hash-pinned, read-only set labeled once per rotation; rules may **never** be tuned against it. Leakage prevention: (a) feedback capture writes to the dev split only — holdout membership is assigned by a one-time deterministic hash at rotation time, published with a version tag; (b) CI rejects any commit touching holdout files in the same change-set as rule/analyzer code; (c) the holdout is consumed only by the `Evaluate` gate and its metrics are published as append-only results; (d) rotation is itself a human-approved event recorded in release notes.

## 4.14 EXP-4 — egress safety spot-check protocol (NFR-5 gate)

1. **Seed**: build a fixture repo containing 8 sentinel secrets spanning all classes: `redis://default:s3ntinel-hunter2@10.0.0.7:6379/0` (S1), `REDIS_URL=redis://…sentinel…` (S2), a 32-char high-entropy quoted literal (S3), `AKIA…`-shaped key (S4), `ghp_`+36 chars (S4), `sk-ant-sentinel…` (S4), a two-segment JWT (`eyJ…eyJ…`), and a PEM private-key block.
2. **Run**: `redis-intel query "classify wrapper in cache.ts" --mode constrained --audit-capture-dir <scratch>`. The capture flag writes the exact serialized request bodies that would be sent to the provider into `<scratch>` (harness-only; the permanent audit log stays hash-only).
3. **Assert**: for each sentinel, `grep -r <sentinel> <scratch>` → **0 matches**; permanent log greps → 0 matches AND `redaction_counts` shows ≥1 replacement for at least S1, S2, S4; `ordering_violation == false` on every record.
4. **Fail condition**: ANY sentinel match ⇒ redaction-ordering bug ⇒ the change under test is blocked; re-run `doctor --security` idempotence check to localize the leaking stage.
5. **Cadence**: runs in the hardening phase and on every change to redaction patterns, sanitization classes, or prompt assembly. Class S3's entropy threshold is tuned here (false-positive rate on the corpus, `[EXPERIMENT REQUIRED]`).

## 4.15 Section 4 decisions summary

Diagram (a) constrained reasoning loop, provider interface contract (§4.2), token table (§4.6), learning-loop workflow + holdout gate (§4.13), sanitization pipeline (§4.8), redaction classes S1/S2/S4 + choke point (§4.9), sandbox core posture (§4.10), resource caps (§4.11), egress audit schema (§4.13), zero-call enforcement (§4.12): `[RECOMMENDED]`. Context budget caps (§4.4) and weaker-vs-stronger routing (§4.5.4): `[PROVISIONAL]`. S3 entropy thresholds: `[EXPERIMENT REQUIRED]`. Provider constants (§4.3): `[RECOMMENDED]` facts from primary-source research.


# SECTION 5 — Architecture Decision Records and Evaluation Suite (FR-34)

## 5.1 ADR 01 — Core Runtime Implementation Language (NFR-7, AC-12)

**Problem.** NFR-7 fixes the runtime's own implementation language as **Python** (user answer q2: "Python is a fixed requirement, not a free choice"). The design freedom therefore lies entirely *within* Python: which parser-binding strategy, which packaging toolchain, and what cold-start/distribution posture the MVP ships. The MVP's *target* analysis language (TypeScript/Node) is a separate decision — ADR 02.

**Credible alternatives (within Python).**

| Variant | Mechanism | For | Against |
|---|---|---|---|
| **a** | tree-sitter via `tree-sitter-language-pack` pinned wheels [S4][S5] — `tree-sitter-typescript@0.23.x` (with `tsx` as a *separate* grammar per [S4]), plus `tree-sitter-javascript` and `tree-sitter-python` prebuilt; grammar versions pinned in `uv.lock` | Uniform grammar API across languages; no native compilation at install time (prebuilt wheels); active upstream maintenance; grammar version is a first-class cache-key input (§2.6), so a grammar bump is a deliberate invalidation, never a silent behaviour change | Binding layer adds a thin indirection between Python and the C grammar; version pins must be tracked |
| b | Per-grammar PyPI wheels installed individually (`pip install tree-sitter-typescript` etc.) | Simpler install; no monolithic pack dependency | Version skew across packages; no single lock surface; the language-pack exists precisely to solve this |
| c | Python `ast` stdlib for a Python-target MVP | Zero new dependency | Rejected: the highest-value rule categories (cache-aside invalidation gaps, TTL inconsistency) concentrate in app-tier TS codebases [S36]; a Python-target MVP would still need tree-sitter machinery later for TS — paying the cost twice |
| d | Native compiler toolchains (tsc, pyright) as parse oracles | Maximum language fidelity | Heavy runtime dependency, licensing surface, and a fundamentally different analysis model — violates the FR-7 simplicity discipline |

**Packaging sub-decision (within variant a).** `uv` for development and lock surface (`uv.lock` committed; `pyproject.toml` declares the grammar-wheel pins), with `pip` as the documented fallback install path. Cold-start posture: CLI entry imports lazily per subcommand so `redis-intel doctor` and `--help` do not load grammar wheels — target < 300 ms `[PROVISIONAL]`. Distribution for the MVP is a source install (`uv pip install -e .`); wheel/PyPI publishing is a future-implementation concern (deployment is explicitly out of scope per D-6) and is recorded here as an honest ADR 01 trade-off, not a Phase 0–8 deliverable.

**Recommendation.** Variant (a): `tree-sitter-language-pack` pinned wheels, grammar versions in `uv.lock`, packaging via `uv` with lazy per-subcommand CLI imports.

**Tradeoffs.** The binding indirection is real but bounded: tree-sitter's grammar API is stable across languages, and the wheel pin discipline (T1) converts grammar drift from a silent correctness risk into a deliberate cache-invalidating event. The uv lock surface adds one artifact to review but eliminates "works on my machine" grammar-version drift.

**Reversibility.** The `LanguageFrontend` protocol (§2.1) isolates grammar choice behind one interface; swapping the binding strategy changes only the frontend package, not the IR or analyzer layers. Packaging swap (uv ↔ pip) is a toolchain change, not an architectural one.

**Status.** `[RECOMMENDED]` — Python is a fixed constraint (not evaluated as an open choice); the within-Python variant evaluation above is complete and the chosen variant has no unresolved dependency.

---

## 5.2 ADR 02 — Target MVP Source Language & Parser Frontend (FR-9, FR-10, NFR-8, AC-4)

**Problem.** The evaluation corpus is bilingual by requirement (NFR-8: ≥1 TypeScript/Node repo AND ≥1 Python repo), but FR-9 requires selecting **exactly one** MVP frontend language from four candidates (Python, JavaScript, TypeScript, TSX) evaluated across four axes (parser maturity, interprocedural data-flow feasibility, runtime typing limits, Redis client surface area). The tension: a bilingual corpus validates the runtime without the runtime parsing both languages at MVP.

**Four languages × four axes:**

| Language | Parser maturity | Interprocedural data-flow feasibility | Runtime typing limits | Redis client surface area |
|---|---|---|---|---|
| **TypeScript** | tree-sitter-typescript@0.23.x mature [S4]; tsx as a separate grammar [S5] | Import graph resolvable one hop via tree-sitter query captures; call edges derivable from the AST; wrapper propagation bounded at depth 2 [S45][S46][S47] | Static types erased at runtime — analysis operates on the AST, not runtime types; this is a *feature* (no type-checker dependency) | **ioredis + node-redis v4/v5** (D2): `new Redis(options)`, `createClient()`, `createCluster()`, `pipeline()`/`multi()`/`exec()`, `eval`/`register_script`, `publish`/`subscribe`; node-redis has **no `.pipeline()`** (same-tick auto-pipelining) [S11][S14] |
| **JavaScript** | Same grammar family (`tree-sitter-javascript`); `.js` and `.mjs` handled | Same AST query surface as TS minus type annotations; import resolution one hop | No type information at all — dynamic typing increases resolver ambiguity, driving more escalations to UNKNOWN | Same client surface (ioredis/node-redis are JS-first) |
| **Python** | `tree-sitter-python` mature [S4] | f-string interpolation and decorator patterns resolvable; `redis-py` client catalog is well-bounded | Dynamic typing; `redis-py`'s `Redis(...)` construction is the dominant pattern | `redis-py`: `Redis(...)`, `connection.pipeline()`, `pipe.watch()/multi()`, `register_script()`+Lua [S37] — deferred to the first expansion frontend, not MVP |
| **TSX** | `tree-sitter-typescript` with `tsx` grammar registered *separately* [S4][S5] | Same as TS for non-JSX scopes; JSX expression containers add interpolation slots for key templates | Same as TS | Same client surface |

**Evaluation.** The MVP frontend is **TypeScript/Node family (`.ts` + `.tsx` + `.js`)** via tree-sitter pinned wheels, with `tsx` registered as a distinct grammar (a JSX file is not a `.ts` file — treating them as one grammar conflates syntax error recovery and interpolation-slot extraction [S4][S5]). **Python is corpus evidence only at MVP, not a second frontend** (D-5): the rq corpus [S37] validates that the IR schema and the Finding contract are language-agnostic without the runtime shipping a Python parser at MVP. The `tree-sitter-python` frontend is the first post-MVP expansion behind the identical `LanguageFrontend` protocol — no core rewrite, validated against the rq corpus before any rule is enabled for it.

**Client-pattern set (D2).** ioredis + node-redis v4/v5, with one-hop wrapper propagation and the round-2 DEPTH correction: wrapper-propagation edges carry a DEPTH attribute in `evidence_json`; bullmq verified at depth 2 (`RedisConnection` → ioredis-client Proxy adapter → raw ioredis [S45][S46][S47]); analyzers resolve to depth 2, deeper or dynamically constructed indirection escalates to `MODEL_HYPOTHESIS`/`UNKNOWN` — never a silent drop.

**UNKNOWN rule (FR-10).** Where the frontend cannot statically resolve an expression — dynamic key concat, wrapper depth > 2, unresolvable interpolation slot — it emits a partial node or an explicit `UNKNOWN`-tier IR row with the unresolved span recorded; it never silently drops the callsite. Escalation path: unresolved → typed `unknowns` result (§2.8) → `MODEL_HYPOTHESIS` candidate (constrained mode) → human `learn` gate for any tier transition.

**Tradeoffs.** Choosing TS/Node as the MVP frontend means the Python corpus (rq) exercises the *schema* and *contract* generality but not Python-specific analyzer precision — stated honestly: Python-specific rule precision is validated post-expansion, not claimed at MVP. The bilingual corpus requirement (NFR-8) is satisfied by corpus coverage, not by dual frontend shipping.

**Reversibility.** Adding the Python frontend is additive: a new `LanguageFrontend` implementation, new grammar wheels, new client catalog rows — no change to the IR schema, the analyzer framework, or the storage engine.

**Status.** `[RECOMMENDED]` — one MVP frontend language selected (TypeScript/Node family); four languages evaluated across four axes; UNKNOWN rule explicit; the bilingual corpus is satisfied by evidence, not by dual parsing.

---

## 5.3 ADR 03 — Persistence & Graph Storage Engine (FR-12, FR-21, FR-23; includes the MVP analyzer subset D3 and epistemic stamping D6)

**Problem.** Three coupled decisions determine what the runtime persists and how reliably: (a) which storage engine holds the IR and the five graph projections (FR-12 requires the SQLite-vs-in-memory-vs-graph-engine comparison); (b) which analyzer subset ships at MVP (D3: 4 of 7 candidate rule categories); (c) how epistemic tiers are stamped and enforced on persisted claims (D6). These are one ADR because the analyzer subset determines the finding population, the storage engine determines the traversal cost that gates rule scope, and the epistemic mechanism is enforced by the storage layer's single-writer discipline.

**Credible alternatives (storage engine, FR-12).**

| Option | Mechanism | For | Against |
|---|---|---|---|
| **a** | Single SQLite file, WAL mode, stdlib `sqlite3`, one writer (C-5); one `edges` adjacency table with five projections as SQL views; recursive CTEs for depth-3 traversal; FTS5 for symbol search; composite cache keys + `db_revision_counter` for transient cache epochs | Zero-install, single-file, transactional findings+artifacts coupling, CTE joins over the full node space; the five projections (§2.5) are views, not copies — zero divergence by construction; NFR-1/2/3 envelope arithmetic is feasible (§2.7) | Recursive CTE latency at 5–10M edges is the one genuinely unmeasured number — gated by EXP-1 |
| b | Content-addressed filesystem blobs (one file per IR slice/finding set) | Trivially content-addressable cache | No transactional coupling between findings and artifacts; no CTE joins — key-pattern traversal requires loading and joining blobs in Python; not viable for NFR-3 |
| c | Hybrid: SQLite canonical + filesystem blob cache | Two-tier caching | Two stores to keep consistent; the composite cache key already gives content-addressing inside SQLite — the hybrid adds complexity without a requirement |
| d | Specialised graph engine (DuckDB, Kùzu, embedded Neo4j) | Native graph queries | New runtime dependency; violates FR-7 (no specialised graph DB without proven simpler-baseline failure — EXP-1 *is* that proof attempt); the one `edges` table already serves all five projections uniformly |

**Recommendation.** Option (a): single SQLite file, WAL mode, one `edges` adjacency table, five projection views, recursive CTEs, FTS5, composite cache keys. **Escalation ladder (EXP-1 gated, §5.6.8):** if recursive-CTE p95 > 2 s at the envelope, escalate in order: closure tables → materialised projections → only then a specialised graph engine, and only with a recorded simpler-baseline failure justifying the FR-7 exception. Each rung is measured before adoption.

**MVP analyzer subset (D3).** Exactly **4 of 7** candidate rule categories, ranked by value × precision ÷ cost (FR-15):

| Rank | Rule | Category | Why selected |
|---|---|---|---|
| 1 | `INV-002` | Cache-aside invalidation gaps | Highest engineering value (stale-cache bugs); `WRITES`+`INVALIDATES` edges are deterministic facts |
| 2 | `TTL-001` | Missing/inconsistent TTLs | Cheapest, most precise (TTL-arg presence directly observable; ceiling `DETERMINISTIC_FACT`) |
| 3 | `NS-003` | Namespace/interpolation mismatches | Writers/readers building different templates for the same logical key; medium precision, high frequency |
| 4 | `RACE-004` | Non-atomic read-modify-write | `get`→compute→`set` without `multi`/Lua/`WATCH`; well-bounded from IR op sequences |

**Deferred with named revisit triggers** (non-goals, not silent gaps): serialization mismatches (needs cross-frontend type surface), unbounded command loops / N+1 hot keys (needs a cost model), connection pool leaks (needs object lifetime tracking). Each lands as an additive analyzer module when its prerequisite lands — no schema change required.

**Epistemic stamping (D6).** Tier is a CHECK-constrained column + provenance on every claim-bearing row; only C-2/C-3 may write `DETERMINISTIC_FACT`; `MODEL_HYPOTHESIS` rows carry provider + verification-report provenance; tier transitions occur only via re-derivation or the human `learn` gate (FR-29). Enforced by the single-writer store — no code path exists for a model output to be inserted at a higher tier.

**Tradeoffs.** The single-SQLite choice bets that recursive CTEs at 5–10M edges stay inside the 2-second budget — the one genuinely open performance question, resolved by EXP-1 before analyzer implementation begins (Phase 0). The 4-rule subset is deliberately narrow: each rule earns its complexity by the ablation suite (§5.6.7), not by assumption.

**Reversibility.** The escalation ladder is ordered simplest-first: closure tables and materialised projections are SQLite-native patterns that don't change the schema, only the query strategy. A specialised graph engine is the last resort, justified only by a recorded EXP-1 failure.

**Status.** `[RECOMMENDED]` — storage engine selected; analyzer subset = 4 rules with named deferrals; epistemic stamping mechanism specified. The CTE latency number is `[EXPERIMENT REQUIRED]` (EXP-1, Phase 0).

---

## 5.4 ADR 04 — LangGraph Adoption Boundary (FR-26, AC-9)

**Problem.** FR-26 requires evaluating LangGraph strictly as an optional library for bounded multi-step reasoning subgraphs and proving or disproving that simple state machines plus the deterministic scheduler make it unnecessary for the MVP.

**Credible alternatives.**

| Option | Mechanism | For | Against |
|---|---|---|---|
| **a** | Hand-rolled request-scoped state machine + DAG scheduler in C-4 (selected) | 7 named states (FR-17) implemented directly; topological/priority scheduling over the TEG; request-scoped checkpoints persisted to the same SQLite store; zero-LLM guarantee (NFR-6) enforced by a state-machine guard, not a framework hook | ~300–500 lines of owned, tested scheduler code; no external framework dependency over the system's most critical loop |
| b | LangGraph for the reasoning subgraph only | Battle-tested checkpoint backends; time-travel replay | LangGraph's own docs position it for "advanced needs" beyond a request-scoped loop [S24]; the MVP's reasoning subgraph is one escalate→verify→retry cycle (§4.1) — the framework's abstraction buys nothing the hand-rolled loop doesn't already do |
| c | LangGraph for the whole control loop | Declarative state transitions | The control loop is mostly deterministic (7 of 10 lifecycle steps are pure Python); wrapping it in a graph framework obscures the zero-LLM guarantee and adds a dependency over the enforcement point |

**Recommendation.** Option (a): hand-rolled. **Post-MVP adoption triggers** (any one suffices): (i) runs must survive process crashes mid-request across sessions (durable cross-process resume with battle-tested checkpoint backends); OR (ii) time-travel replay of task-graph state is required by a downstream consumer; OR (iii) deep LangChain agent integration is requested. Absent any trigger, the hand-rolled loop stands.

**Tradeoffs.** The hand-rolled scheduler is ~300–500 lines of code that must be owned and tested — cheaper than a fast-moving 0.x abstraction over the system's most critical loop, and the only way to guarantee the NFR-6 zero-LLM enforcement is structural (a state-machine guard), not conventional.

**Reversibility.** The control loop's lifecycle steps and the TaskNode contract are framework-agnostic; if a trigger fires, the escalate→verify→retry cycle maps onto a LangGraph subgraph without changing the TaskNode schema or the verifier.

**Status.** `[RECOMMENDED]` — rejected for MVP; the three post-MVP triggers are named and concrete.

---

## 5.5 ADR 05 — AgentField & Deployment Architecture (FR-27, AC-9)

**Problem.** FR-27 requires evaluating AgentField (`github.com/Agent-Field/agentfield`) against its actual codebase and docs, contrasting a standalone local CLI against an AgentField service deployment, and stating the exact scale or operational triggers that would justify adopting it post-MVP.

**Credible alternatives.**

| Option | Mechanism | For | Against |
|---|---|---|---|
| **a** | Standalone local Python CLI (selected) | Zero deployment surface; single-user, single-repo, request-scoped execution; the CLI is the entire user interface (C-8) | No multi-consumer routing, no durable fan-out, no DID/VC audit — none of which any FR demands at MVP |
| b | AgentField service deployment | Production REST infrastructure: routing, durable fan-out, DID/VC audit, canaries | Go control plane, pre-1.0 (`v0.1.143-rc.4`, "not recommended for production"), 40–170 MB binaries [S21][S22][S23]; adopting it imports a service deployment against the no-microservices prohibition (FR-7) and solves problems absent at single-dev/single-repo/request-scoped scale |

**Recommendation.** Option (a): standalone local Python CLI now. **Post-MVP adoption triggers (3, from T5)** — any one suffices: (a) ≥2 services/teams consume analysis via a stable authenticated REST surface; (b) sustained fan-out ≥ ~1k concurrent invocations beyond in-process queue capacity; (c) durable multi-hour crash-resumable runs with webhook callbacks + signed audit trails required by a compliance regime.

**Tradeoffs.** The CLI posture means no network surface, no auth layer, no service lifecycle — all of which are unnecessary at MVP scale and would be speculative infrastructure (FR-7 discipline). The trade-off is honest: if any trigger fires, the runtime's component protocols (C-1..C-8) are the seam at which a service wrapper attaches.

**Reversibility.** The C-8 CLI is a thin composition root over the component protocols; a future AgentField integration would wrap C-4 (control loop) and C-8 (CLI) behind a service boundary without touching C-1..C-7.

**Status.** `[RECOMMENDED]` — standalone CLI for MVP; AgentField deferred with 3 named, concrete triggers.

---

## 5.6 Benchmark and ablation suite

### 5.6.1 Evaluation corpus (NFR-8 bilingual; resolved by approved plan revision 1) `[RECOMMENDED]`

**Real-world anchors:**

| Repo | Family | Licence | Role | Evidence |
|---|---|---|---|---|
| taskforcesh/bullmq | TS/Node (ioredis default; node-redis + Bun adapters) | MIT [S36] | TS/Node anchor — both Node client families in one MIT repo; verified two-layer wrapper (`RedisConnection` → ioredis-client Proxy adapter → raw ioredis [S45][S46]) | Source-verified |
| rq/rq | Python (redis-py) | BSD-3-Clause [S37] (GitHub API reports "Other"/NOASSERTION — detector false-negative on the BSD-3 header; licence text verified) | Python anchor — corpus evidence only (D-5: no Python frontend at MVP); `rq/queue.py` patterns exercise the IR schema's language-agnostic claim | Source-verified |
| joshuaslate/type-cacheable | TypeScript | MIT [S40], actively maintained | TS alternate anchor — promoted from the round-2 shortlist | Source-verified |
| a-luna/fastapi-redis-cache | Python | MIT [S39] | Listed, **not primary** — stale (~9 months since last push) | Source-verified |
| outline/outline | TS/Node (ioredis) | **Business Source License 1.1** [S38] | **EXCLUDED** — the licence explicitly states it "is not an Open Source license"; fails the permissive criterion. Referenced for pattern study only, never shipped as an evaluation anchor | Source-verified |

**Corpus selection was resolved by approved plan revision 1**: bullmq + rq as primary anchors, type-cacheable as the TS alternate, outline excluded per BSL 1.1.

**Synthetic corpus (primary ground-truth vehicle) `[RECOMMENDED]`:**

Deterministically generated TS/Node + Python repos with injected defects + an injection manifest (= ground truth). Tiers matching the NFR-4 envelope:

| Tier | Scale | Purpose |
|---|---|---|
| S | ~100 files / ~10k LOC | CI smoke |
| M | ~1k files / ~100k LOC | Regression + EXP-3 pre-scale |
| L | ~10k files / ~1M LOC | NFR-1/2/3 measurement, ABL-1..8, EXP-1/EXP-3 |

Mix per tier: ~60% neutral filler (correct cache-aside `setex` after DB write, consistent TTLs/templates — negative controls), ~30% pattern-rich (pipelines, Lua, pubsub, one-hop wrappers, TSX + plain `.ts`, f-string Python), ~10% planted defects (≥25 per rule at tier L) with known file/line spans in the manifest. ~10% escalation cases unresolvable statically (two-hop wrapper indirection, fully dynamic key concat) whose correct runtime output is `UNKNOWN`/`MODEL_HYPOTHESIS` — never a silent drop (FR-10). Tier L ships a pinned seed, a scripted 20-file commit series, and a checksum manifest (byte-identical repetitions).

### 5.6.2 Ground-truth labeling rules `[RECOMMENDED]`

Each labeled item receives **exactly one** tier — the highest a correct, complete analysis could justify **without model reasoning**:

| Tier | Meaning | Example |
|---|---|---|
| `DETERMINISTIC_FACT` | Directly observable in AST/IR, zero inference | TTL-arg presence at a resolvable callsite; literal key template; command method on a resolvable client instance; presence/absence of `del` in the same scope |
| `STATIC_INFERENCE` | Correct via bounded data-flow, not visible at one callsite | Template via interpolation of resolvable locals/params; invalidation-absence across the flow graph; one-hop wrapper resolution; namespace mismatch comparing two resolvable templates |
| `MODEL_HYPOTHESIS` | Only resolvable by reasoning beyond static analysis | Deep indirection, semantic intent, coupling without call edges — excluded from deterministic-mode recall denominators; reported as a separate recall line; the creditable domain of Constrained Reasoning Mode |

**Precedence**: `DETERMINISTIC_FACT` > `STATIC_INFERENCE` > `MODEL_HYPOTHESIS`; on disagreement, record the **lower** tier.

**Procedure**: synthetic ground truth is by construction (injection manifest authoritative; disputes = generator bug → regenerate + re-hash). Real-world repos: tool-assisted candidate listing → **double-entry** labeling by qa + backend_lead, independent and blind to runtime output → **Cohen's κ ≥ 0.70** required to accept a repo label set `[PROVISIONAL]` → disputes adjudicated by a third annotator; unresolved disputes dropped and recorded as coverage gaps. Label records carry `repo, path, span, kind, tier, annotators, resolution`, versioned with the corpus.

### 5.6.3 Correctness metrics (exact formulas) `[RECOMMENDED]`

A Finding matches labeled defect *d* iff `rule_id` equals *d*'s rule id AND any `location` span overlaps *d*'s manifest span (one-to-one greedy match by span-overlap then confidence).

| Metric | Formula | Gate |
|---|---|---|
| Precision | TP/(TP+FP) — per rule_id and macro-averaged | Phase 2: ≥ 0.90 on tier-S/M synthetic `[PROVISIONAL]` |
| Recall | TP/(TP+FN) — per rule_id and macro-averaged | Phase 2: ≥ 0.95 on `DETERMINISTIC_FACT` labels `[PROVISIONAL]` |
| F1 | 2·P·R/(P+R) | Reported, not gated |
| path_accuracy(q) | \|{p ∈ R(q) : p ∈ E(q)}\| / \|E(q)\| where E(q) = ground-truth path set, R(q) = returned paths; a path matches iff node sequence AND all edge types match exactly | Phase 4: = 1.0 on tier-S fixtures |
| path_spurious_rate | \|{p ∈ R(q) : p ∉ E(q)}\| / \|R(q)\| | Reported alongside path_accuracy |
| UCR (unsupported-claim rate) | 1 − supported_claims/total_claims; a claim is *supported* iff (i) tier ≤ emitting task/rule ceiling, (ii) every cited IrId resolves in the store, (iii) every quoted literal is a verbatim substring of the evidence text | **UCR = 0** (Deterministic Mode); **UCR ≤ 0.05** (Constrained/Advanced) `[PROVISIONAL]` |
| stale_recall | correctly_demoted_stale / should_be_stale (incremental runs, scripted commits) | **Hard gate: = 1.0** — a stale miss is a correctness bug, not a tuning knob |
| stale_FPR | wrongly_demoted_stale / correctly_fresh_total | **Hard gate: = 0.0** |
| fresh_carry_accuracy | correctly_carried_fresh / should_remain_fresh | Reported |

### 5.6.4 Token accounting metrics (exact formulas) `[RECOMMENDED]`

Collection mechanism: every provider call writes one egress-audit record (§4.13) with prompt hash, redaction replacement count, and the full provider usage object; the normalizer reads audit records + provider usage fields.

| Metric | Formula / source |
|---|---|
| `tokens_total(run)` | Σ (prompt_tokens + completion_tokens) over provider usage |
| `tokens_cached(run)` | OpenAI `usage.prompt_tokens_details.cached_tokens` [S41][S50] + Anthropic `cache_read_input_tokens` [S43] |
| `tokens_cache_write(run)` | Anthropic `cache_creation_input_tokens` (billed at 1.25× base input for ≤5-min TTL, 2× for 1-h TTL [S43]); OpenAI has no write counter (bills as uncached input — recorded 0, noted) |
| `bytes_sent_to_llm(run)` | Σ serialized request-payload bytes over audit records, **post-redaction** (NFR-5 sampling surface) |
| `cost(run)` | Σ per call: uncached_in×p_in + cached_in×p_cache_read + cache_write×p_cache_write + output×p_out; prices pinned in the benchmark manifest (model id + date + price table) |
| `cost_per_verified_finding` | `cost(run)/V` where V = findings with `lifecycle ∈ {supported, verified}` AND (tier ∈ {`DETERMINISTIC_FACT`, `STATIC_INFERENCE`} OR `MODEL_HYPOTHESIS` passing the OutputVerifier); **V=0 ⇒ reported n/a, never divided silently** |

Normalization is mandatory: OpenAI automatic caching applies at ≥1,024-token prefixes in 128-token increments [S41]; Anthropic supports ≤4 explicit `cache_control` breakpoints with per-model minima 1,024 tokens (Sonnet) / 4,096 tokens (Opus, Haiku 4.5) [S43]. Cache-hit rate is measured per run, never assumed.

### 5.6.5 Baseline protocol vs general-purpose coding agent `[RECOMMENDED]`

- **Baseline**: general-purpose coding agent, exact harness + model pinned in the benchmark manifest; **model tier identical** to the runtime's provider model per campaign (one Anthropic campaign + one OpenAI campaign).
- **Objectives** (identical corpus): O1 TTL defects; O2 invalidation gaps; O3 namespace mismatches; O4 non-atomic RMW races; O5 three key-traversal questions (writers/readers/TTL-setters/invalidation paths).
- **Controlled prompt**: fixed template with rule definitions identical to the analyzer specs; no corpus-specific hints; prompt + model ids in the manifest.
- **N repetitions**: baseline N=5; runtime-constrained N=5; runtime-deterministic N=1 (determinism asserted identical across 3 verification runs).
- **Ordering/randomization**: file/commit processing order randomized per repetition from a fixed seed list; baseline and runtime repetitions interleaved in one campaign (provider-load drift control); each repetition starts cold-cache (≥10 min gap or fresh cache key).
- **Advantage claim rule (OBJ-4)**: defensible iff runtime matches baseline recall within **−5 pts** while strictly better on **≥2 of** {UCR, tokens_total, cost, wall time} `[PROVISIONAL]`.
- **Reference hardware profile**: MacBook-class, 8 performance cores, 32 GB RAM, Apple-Silicon Python 3.12, SQLite on APFS — **default adopted by approved plan revision 1, pending user override**. NFR-1/2/3 numbers are unfalsifiable without a named profile; any override changes the measurement conditions, not the targets.

### 5.6.6 Ablation suite — exactly 8 (ABL-1..8) `[RECOMMENDED]`, thresholds `[PROVISIONAL]`

Each ablation = one build-flag disabling exactly one subsystem; procedure: full-index + O1–O5 on tier-L (+ tier-S smoke), N=3, randomized ordering, full runtime as control. No measurable degradation ⇒ the subsystem failed to earn its complexity — reported honestly.

| # | Ablated subsystem | Hypothesis | Procedure delta | Primary metric | Expected effect |
|---|---|---|---|---|---|
| ABL-1 | Persistent IR (stateless per-query re-analysis) | Persistence amortizes index cost (FR-21) | O1–O5 fresh process, no store | query p95; tokens | p95 ≥10× NFR-3 (>20 s vs ≤2 s); tokens ≥5× |
| ABL-2 | Incremental invalidation (full rebuild every run) | Composite-key deltas are orders faster (FR-23) | 20-file commit; full rebuild | incremental wall time | ≥100× (>500 s vs ≤5 s, NFR-2) |
| ABL-3 | Epistemic tiering (all claims single-tier) | Tiering stops model guesses consumed as facts (FR-8) | constrained O1–O4 vs ground-truth tiers | UCR; tier violations | UCR ~0 → ≥0.15 |
| ABL-4 | Constrained-reasoning mode (deterministic only) | Bounded LLM fallback buys recall on `MODEL_HYPOTHESIS` items (FR-24) | O1–O4 on the escalation-case set | recall on `MODEL_HYPOTHESIS` labels | Δrecall ≥ +10 pts at UCR ≤ 0.05 |
| ABL-5 | Evidence packages (full-file dumps) | Compact IR slices cut tokens without recall loss (FR-25) | constrained O1–O4, dump whole files | tokens/bytes; cost | tokens ≥3× at ≤1 pt recall gain for packages |
| ABL-6 | Prompt-caching layout (variable-first prompts) | Stable prefix earns cache discounts [S41][S43] | same calls, shuffled ordering | cached ratio; cost | cached ratio ≥30 pts lower; cost ≥1.5× |
| ABL-7 | Dedup/cache keys (every task re-executes) | Content-addressed cache kills redundant work (FR-18/FR-23) | O1–O5 twice; cache off in run 2 | run-2 tokens/wall time | ≥80% deterministic tasks cache-served ⇒ ≥5× run-2 cost |
| ABL-8 | Evidence-aware stopping (fixed max iterations) | Stopping bounds spend at <5% recall loss (FR-20) | constrained O1–O4, fixed max iterations | tokens; cost; recall delta | ≥2× token spend at ≤5 pts recall difference |

### 5.6.7 EXP-1..4 integration gates `[RECOMMENDED]`

| EXP | Gate condition | Gates | Fail action |
|---|---|---|---|
| **EXP-1** (recursive-CTE traversal p95, 5–10M edges, hop depth 3) | PASS iff p95 ≤ 2 s | **NFR-3** | Storage revisit — escalate per the ladder in §5.3 (closure tables → materialised projections → graph engine, only with recorded simpler-baseline failure) |
| **EXP-2** (template precision, 50 labeled bullmq callsites) | PASS iff precision ≥ 80% `[EXPERIMENT REQUIRED]` | MVP rule scope (D3) | Fail ⇒ literal-key sites + UNKNOWN escalation for unresolved templates |
| **EXP-3** (incremental wall-clock, 10k-file repo, 20-file commit) | PASS iff ≤ 5 s AND stale_recall = 1.0 AND stale_FPR = 0.0 | **NFR-2** + stale correctness | Invalidation redesign |
| **EXP-4** (egress safety spot-check, seeded sentinel secrets) | PASS iff 0 unredacted matches | **NFR-5** — zero tolerance | Redaction-ordering bug ⇒ change under test blocked; re-run `doctor --security` to localize the leaking stage |

All four experiments are executable only after the runtime is implemented; the suite design is fixed now so the runtime's testable seams are designed in, not retrofitted.

### 5.6.8 Per-phase completion test gates (Phases 0–8) `[RECOMMENDED]`

| Phase | Gate |
|---|---|
| 0 Discovery/Evaluation Foundation | EXP-1 and EXP-2 executed with recorded numbers; storage and rule-scope decisions made from them; corpus generator + manifest schema deterministic (same seed → byte-identical repo) |
| 1 IR Extraction | Per-grammar fixture corpus green (incl. TSX-as-separate-grammar [S4][S5]); 14 IR entities round-trip byte-equal; unresolved nodes → `UNKNOWN` rows, 0 silent drops |
| 2 Deterministic Analyzers | 4 rule fixtures green; tier-S/M synthetic precision ≥ 0.90, recall ≥ 0.95 on `DETERMINISTIC_FACT` labels `[PROVISIONAL]`; Finding fields distinct/populated; UCR = 0 |
| 3 Incremental Storage | EXP-3 green at tier L; full-rebuild fallback triggers on all five conditions; composite-key invalidation touches no unaffected findings |
| 4 Demand-Driven Planner | All four RetrievalQuery kinds contract-conform; path accuracy = 1.0 on tier-S fixtures; p95 ≤ 2 s at tier M; zero-LLM runs proven via task provenance (NFR-6) |
| 5 Bounded Reasoning | Verifier rejects 100% of the adversarial fixture suite; UCR ≤ 0.05; ABL-3/5/6 show expected directions at tier S; budget exhaustion → bounded partial report, never invented conclusions |
| 6 Controlled Learning | Locked holdout frozen; confirmed FPs become regression fixtures; zero benchmark leakage (content-hash verified); no autonomous self-modification path |
| 7 Hardening | EXP-4 green across ≥3 campaigns; resource-cap paths yield `PARTIAL`/`FAILED` with clean audit; adversarial prompt-injection corpus (comments/strings, Lua bodies) — no behavioural hijack |
| 8 Envelope Certification | Full suite at tier L + real corpus; NFR-1/2/3 measured on the approved hardware profile; ABL-1..8 recorded; baseline comparison complete; every runtime AC executed or explicitly untested-with-reason |

---

# SECTION 6 — Module Map, Implementation Roadmap, Risks, and Approval Checklist (FR-35)

## 6.1 Module map — 8 components

```
redis-intel/
├── pyproject.toml             # uv-managed; grammar-wheel pins in uv.lock (ADR 01)
├── uv.lock
└── redis_intel/
    ├── frontend/              # C-1 Ingestion / language frontend
    ├── ir/                    # C-2 Redis IR extraction
    ├── analyzers/             # C-3 Deterministic analyzer framework
    ├── control/               # C-4 Control loop + Task Execution Graph
    ├── store/                 # C-5 Retrieval / persistence / invalidation
    ├── reasoning/             # C-6 Bounded reasoning provider layer
    ├── governance/            # C-7 Security / governance
    └── cli.py                 # C-8 CLI surface
```

| Module | Purpose | Public interface | Owned state | Depends on | Prohibited responsibilities | Test strategy |
|---|---|---|---|---|---|---|
| **C-1** `redis_intel/frontend/` | Parse target-repo files into syntax trees + normalized raw-call stream; one-hop import resolution | `LanguageFrontend.parse()`, `iter_redis_callsites()`, `iter_scopes()`; `ParseResult` (path, content_hash, grammar_id, grammar_version, unresolved tuple) | Per-file parse cache (transient) | C-7 (sandbox policy) | No IR construction, no SQL, no provider calls, no repo writes | Per-grammar fixture corpus; TSX-as-separate-grammar cases; unresolved-node → UNKNOWN regression |
| **C-2** `redis_intel/ir/` | Turn raw callsites into the versioned, language-agnostic IR (14 entity kinds, typed edges); stamp epistemic tier on every claim; resolve one-hop wrapper indirection (DEPTH attribute) | `IrBuilder.ingest(ParseResult...) -> IrDelta` (upserts + tombstones + schema_version) | IR schema version constant | C-1, C-7 (redaction of conn_config at IR build) | No SQL, no provider calls, no repo writes | 14-entity round-trip byte-equal; wrapper DEPTH escalation fixtures; conn_config redaction assert |
| **C-3** `redis_intel/analyzers/` | Run pattern rules over IR projections; pattern detection separated from severity scoring / impact estimation / remediation generation | Analyzer protocol (rule_id, version, required IR inputs, execution cost, confidence ceiling, caching rules, regression fixtures); emits `Finding` per §2.6 | Rule registry + fixtures | C-2, C-5 (read-only IR access) | No SQL writes, no provider calls, no repo writes | Per-rule fixture suite; precision/recall vs synthetic manifest; Finding-contract field distinctness |
| **C-4** `redis_intel/control/` | Request-scoped state machine (7 states, FR-17); objective→evidence decomposition; deterministic-first scheduling; token budgets; evidence-aware stopping; zero-LLM guard in Deterministic Mode | `ControlLoop.run(question, budget, mode) -> InvestigationReport`; TaskNode schema per §3.4 | Task Execution Graph (persisted to store) | C-3 (analyzer dispatch), C-5 (persistence + retrieval), C-6 (reasoning dispatch), C-7 (egress gate invocation) | No direct SQL (all writes via C-5), no direct provider calls (via C-6), no repo writes | 7-state transition tests; zero-LLM provenance in deterministic mode (NFR-6); budget-exhaustion → bounded partial report |
| **C-5** `redis_intel/store/` | Own ALL SQLite access (WAL mode); canonical IR tables, derived projection views, transient query cache; composite cache keys; git-diff-driven incremental invalidation with full-rebuild fallback | `Store.upsert(IrDelta)`, `Store.run_compiled_query(RetrievalQuery)`, `Store.invalidate(diff)`, `Store.snapshot_epoch()` | The SQLite database file; schema_meta counter; store_manifest digests | None (leaf — consumes IR deltas, serves queries) | No provider calls, no repo writes, no analyzer logic | EXP-3 protocol; five fallback conditions; composite-key invalidation isolation; corruption recovery |
| **C-6** `redis_intel/reasoning/` | Three operating modes (FR-24); provider-agnostic calls with JSON-schema validated outputs; redaction-before-prompt-build; post-call deterministic verification; stable-prefix prompt layout | `LLMGateway.call(prompt, task_schema)`, `PromptBuilder.build(evidence)`, `OutputVerifier.verify(result, evidence)` | Per-task-kind prompt templates; provider config | C-7 (EgressGate is the sole choke point), C-4 (mode + budget enforcement) | No SQL, no repo access, no analyzer logic | Verifier adversarial fixture suite (100% rejection); prompt-layout caching; weaker/stronger routing per §4.5.4 |
| **C-7** `redis_intel/governance/` | Redaction engine (S1–S4 classes) running before any prompt assembly; prompt-injection sanitization (INJ-01..06) of extracted snippet text; read-only sandbox posture; resource caps; egress audit log | `EgressGate.redact(PromptPlan)`, `sanitize_snippet(text)`, `doctor --security` | Redaction pattern tables; audit log | None (leaf — consumed by C-2, C-6, C-4) | No SQL, no provider calls, no repo writes | EXP-4 sentinel-grep protocol (zero tolerance); sanitization ordering; idempotence (`redact(redact(x)) == redact(x)`) |
| **C-8** `redis_intel/cli.py` | The entire user surface: `index [--full|--since]`, `query <q> [--mode]`, `findings`, `explain <key-pattern>`, `doctor`, `learn` (offline, human-gated) | argparse subcommands; stdout JSON for machine consumption | None (composition root) | All of C-1..C-7 | No business logic, no SQL, no provider calls | E2E smoke per subcommand; `doctor` integrity checks; `learn` human-gate assertion |

**Composition rule**: C-8 is the only entry point; C-5 is the only SQL choke point; C-7 is the only egress choke point; C-4 is the only budget/mode enforcement point. No component bypasses another's choke point.

## 6.2 Phased implementation roadmap (Phases 0–8)

| Phase | Deliverables | Dependencies | Parallelizable with | Relative effort | Completion gate (§5.6.8) |
|---|---|---|---|---|---|
| **0** Discovery/Evaluation Foundation | Corpus generator + injection manifest; EXP-1 + EXP-2 harnesses; storage decision confirmed; hardware profile confirmed | none | — | 1–2 wk (assumes 1 experienced Python dev; corpus generator is the bulk) | Phase-0 gate |
| **1** IR Extraction | C-1 (3 grammars) + C-2 (14 entities, typed edges, DEPTH attribute) | Phase 0 | C-7 skeleton (redaction tables) | 2–3 wk (tree-sitter query authoring is the bulk; TSX separate grammar adds ~20%) | Phase-1 gate |
| **2** Deterministic Analyzers | C-3 (4 rules: INV-002, TTL-001, NS-003, RACE-004) + Finding contract | Phase 1 | C-5 store schema + bulk-insert path | 2 wk (rule logic is bounded once IR lands) | Phase-2 gate |
| **3** Incremental Storage | C-5 complete: WAL, composite keys, invalidation DAG, fallback conditions, FTS5 | Phase 2 | C-6 provider adapter + prompt templates | 2 wk (invalidation DAG is the risk item) | Phase-3 gate |
| **4** Demand-Driven Planner | C-4: state machine, TEG, scheduler, stopping rules, zero-LLM guard | Phase 3 | C-7 sanitization pipeline + EXP-4 harness | 2–3 wk (scheduler + stopping rules are the design-critical items) | Phase-4 gate |
| **5** Bounded Reasoning | C-6 complete: 3 modes, OutputVerifier, weaker/stronger routing, prompt-caching layout | Phase 4 | ABL-3/5/6 harnesses | 2 wk | Phase-5 gate |
| **6** Controlled Learning | `learn` subcommand; holdout freeze; feedback→regression-fixture pipeline | Phase 5 | — | 1 wk | Phase-6 gate |
| **7** Hardening | `doctor` integrity checks; resource-cap paths; adversarial prompt-injection corpus; EXP-4 campaigns | Phase 6 | — | 1–2 wk | Phase-7 gate |
| **8** Envelope Certification | Full-suite tier-L + real-corpus run; NFR-1/2/3 measurement; ABL-1..8; baseline comparison; final report | Phase 7 | — | 1 wk | Phase-8 gate |

**Total relative effort**: ~14–18 weeks for one experienced Python developer, assuming the ADR-01/02 technology choices hold and no EXP-1 storage escalation is needed. Parallelizable tracks (C-7 alongside C-1/C-2; C-5 schema alongside C-3; C-6 alongside C-4) compress the critical path by ~2–3 weeks with a second contributor.

## 6.3 Ranked risk register

| Rank | Risk | Likelihood | Impact | Mitigation | Owner |
|---|---|---|---|---|---|
| 1 | Recursive-CTE p95 > 2 s at 5–10M edges (EXP-1 fail) | Medium | High — NFR-3 miss, storage redesign | Escalation ladder (§5.3): closure tables → materialised projections → graph engine, each measured before adoption; EXP-1 runs in Phase 0 before analyzer code | backend_lead |
| 2 | Wrapper-depth distribution wider than 2 (EXP-2 fail: precision < 80%) | Medium | Medium — D2's client-pattern scope narrows | DEPTH attribute on wrapper-propagation edges [S45][S46]; resolve to depth 2, escalate deeper to UNKNOWN/MODEL_HYPOTHESIS; EXP-2 measures the distribution before rules ship | backend_lead |
| 3 | Incremental invalidation misses a stale finding (stale_recall < 1.0) | Low | High — correctness bug, not a tuning knob | Composite cache keys cover content + dependency + schema versions; five fallback conditions trigger full rebuild; EXP-3 hard-gates at 1.0/0.0 | backend_lead |
| 4 | Provider contract drift (OpenAI/Anthropic caching or structured-output changes) | Low | Medium — token accounting + verifier breakage | Provider constants pinned in the benchmark manifest with model id + date; contract tests assert the constants; drift is a visible test failure, not a silent accounting error | security + backend_lead |
| 5 | Redaction ordering violation (unredacted secret reaches a provider) | Low | Critical — NFR-5 breach | Structural enforcement: `EgressGate.redact()` is the sole choke point; transport refuses non-gate-issued bodies; EXP-4 zero-tolerance gate in every campaign | security |
| 6 | Corpus generator nondeterminism (same seed ≠ byte-identical repo) | Low | Medium — ground truth unreliable | Pinned seed; checksum manifest; byte-identical repetition assert in the Phase-0 gate | qa |
| 7 | Double-entry labeling κ < 0.70 on real corpus | Medium | Medium — real-corpus labels rejected | Third-annotator adjudication; unresolved disputes dropped and recorded as coverage gaps, never silently included | qa + backend_lead |
| 8 | TSX grammar separation regressions (TSX parsed as plain TS) | Medium | Medium — FR-9 violation | TSX-as-separate-grammar fixture cases in the Phase-1 gate; grammar_id distinguishes `tsx` from `typescript` in every ParseResult | backend_lead |
| 9 | Token-budget miscalibration (budgets too tight → INCONCLUSIVE floods; too loose → cost overrun) | Medium | Medium — usability | ABL-4/ABL-8 measure the effect; budgets are `[PROVISIONAL]` and tunable; budget exhaustion is a visible stop reason, never a silent truncation | backend_lead |
| 10 | Baseline comparison invalidated by provider drift between campaigns | Low | Medium — OBJ-4 advantage claim unsupported | Model tier pinned per campaign; interleaved ordering; cold-cache starts; advantage-claim rule requires the −5 pts recall + ≥2-of-4 strictly-better condition | qa |

## 6.4 First-3 minimum-viable experiments (design)

### EXP-1 — Recursive-CTE traversal latency (gates NFR-3)

**Question**: does a recursive CTE over the single `edges` adjacency table return a depth-3 traversal within 2 s p95 at 5–10M edges?

**Setup**: synthetic tier-L DB (~10k files → ~2–5M edges); query = Q2 (§2.8): seed on a key pattern, walk `CALLS`/`KEY_FLOW`/`DATA_FLOW` edges up (callers) and down (callees/readers) to depth 3, with the `path`-string cycle guard.

**Measurement**: 100 randomized key patterns, p95 wall-clock of the compiled query, WAL mode, 64 MB page cache, mmap 256 MB (§2.7 pragmas), on the approved hardware profile.

**PASS**: p95 ≤ 2 s → NFR-3 confirmed; no storage escalation needed.

**FAIL — escalation ladder** (in order, each rung measured before the next):
1. **Closure tables**: materialise the transitive closure for the hottest edge types (`CALLS`, `KEY_FLOW`) at index time; trade write cost for read latency.
2. **Materialised projections**: precompute per-pattern result sets for the top-N hottest key patterns; invalidate via the composite-key mechanism.
3. **Specialised graph engine**: only with a recorded simpler-baseline failure justifying the FR-7 exception — a new dependency, a new deployment surface, and a second store to keep consistent.

**De-risk timing**: Phase 0, before any analyzer or planner code exists — a storage redesign at Phase 0 costs days; at Phase 5 it costs the roadmap.

### EXP-2 — Wrapper-depth distribution (gates D3 rule scope)

**Question**: what fraction of bullmq's Redis callsites resolve at wrapper depth ≤ 2, and does template extraction hold precision ≥ 80% at those sites?

**Setup**: 50 labeled bullmq callsites spanning direct construction, one-hop wrappers (module re-exporting a constructed client), and the verified two-layer `RedisConnection` → Proxy adapter → raw ioredis chain [S45][S46]; each labeled with its true wrapper depth and key template.

**Measurement**: run C-2's wrapper propagation + template extraction; measure per-callsite: resolved depth, template correctness, tier assigned.

**PASS**: precision ≥ 80% on resolvable templates → D3's rule scope (4 analyzers) is justified at MVP.

**FAIL**: if depth > 2 sites dominate or template precision < 80%, narrow the MVP rule set — literal-key sites only, with unresolved templates escalated to UNKNOWN/MODEL_HYPOTHESIS. The DEPTH attribute (round-2 correction) already propagates through the IR, so the escalation path exists; the experiment decides whether it is the common case or the exception.

**De-risk timing**: Phase 0, alongside EXP-1 — determines whether the 4-analyzer subset ships or narrows before Phase 2 begins.

### EXP-3 — Incremental re-index latency profile (gates NFR-2 + stale correctness)

**Question**: does a 20-file commit on a 10k-file repo re-index in ≤ 5 s with stale_recall = 1.0 and stale_FPR = 0.0?

**Setup**: tier-L synthetic repo at steady state (full-indexed); apply the scripted 20-file commit series (from the corpus manifest, spanning: modified function bodies, a renamed file, a deleted file, a changed function signature, a modified key template, a grammar-version-relevant syntax change, and a no-op change).

**Measurement**: per commit, wall-clock of: git-diff read → changed-file re-parse → IR-slice rebuild → composite-key comparison → invalidation-DAG walk → finding demotion/carry → commit. Record stale_recall and stale_FPR against the manifest's expected transitions.

**PASS**: wall-clock ≤ 5 s AND stale_recall = 1.0 AND stale_FPR = 0.0 → NFR-2 + stale correctness confirmed.

**FAIL**: if wall-clock exceeds 5 s, profile the phases (parse / IR rebuild / key comparison / DAG walk / finding carry) and optimize the dominant phase — the composite-key design (§2.6) already ensures unaffected regions are never re-analyzed, so a miss is an implementation bug, not a design gap. If stale_recall < 1.0, the invalidation-DAG walk has a coverage gap — fix before Phase 4, not after.

**De-risk timing**: Phase 3 completion gate — EXP-3 green is the Phase-3 exit criterion.

## 6.5 Approval checklist

Items consolidated from every `[APPROVAL REQUIRED]` / approval-gated decision across the document (Sections 1–4 scanned by tag; ADR status tags; D7 items):

| # | Item | Status | Resolution authority |
|---|---|---|---|
| 1 | **Corpus repo selection (R-1)**: bullmq (MIT) + rq (BSD-3) as primary anchors; type-cacheable (MIT) as TS alternate; outline/outline **EXCLUDED** per BSL 1.1 ("not an Open Source license" [S38]) | **RESOLVED** — approved plan revision 1 | User approval at 2026-10-20 |
| 2 | **Reference hardware profile (R-3)**: MacBook-class, 8 performance cores, 32 GB RAM, Apple-Silicon Python 3.12, SQLite on APFS | **Default adopted** by approved plan revision 1 — pending user override; NFR-1/2/3 targets are stated against this profile | User approval at 2026-10-20 (default); user may override |
| 3 | **Runtime implementation language**: Python (NFR-7, user answer q2) — a fixed constraint, not a design choice; within-Python variants evaluated in ADR 01 | **FIXED CONSTRAINT** — not open for approval | User requirement (NFR-7) |
| 4 | **MVP target source language**: TypeScript/Node family via tree-sitter wheels; TSX as a separate grammar; Python as corpus evidence only (D-5/D1, ADR 02) | **RESOLVED** — approved plan revision 1 (ADR 02 `[RECOMMENDED]`) | Plan revision 1 |
| 5 | **MVP client-pattern set**: ioredis + node-redis v4/v5 with one-hop wrapper propagation and DEPTH attribute (D2) | `[RECOMMENDED]` — design-backed, ready for implementation | — |
| 6 | **MVP analyzer subset**: 4 of 7 categories (INV-002, TTL-001, NS-003, RACE-004) (D3) | `[RECOMMENDED]` — EXP-2 gates the scope | — |
| 7 | **LangGraph**: dropped for MVP; post-MVP triggers named (D4, ADR 04) | `[RECOMMENDED]` | — |
| 8 | **AgentField**: deferred; standalone local Python CLI for MVP; 3 adoption triggers named (D5, ADR 05) | `[RECOMMENDED]` | — |
| 9 | **Epistemic stamping mechanism**: CHECK-constrained tier column + provenance on every claim-bearing row (D6) | `[RECOMMENDED]` | — |
| 10 | All remaining `[PROVISIONAL]` numeric thresholds (κ ≥ 0.70, P/R gates, UCR ≤ 0.05, effect sizes, budget caps, ε stopping threshold, scoring weights) and `[EXPERIMENT REQUIRED]` items (EXP-2 precision threshold, S3 entropy thresholds, calibration constants) | **Deferrable to implementation** — each is gated on its named EXP/ABL; none blocks the architecture | Implementation-phase measurement |

**Blocking architectural decisions**: none remain — both D7 items (corpus R-1, hardware profile R-3) were resolved by approved plan revision 1.
**Deferrable implementation choices**: every `[PROVISIONAL]` threshold and `[EXPERIMENT REQUIRED]` item, each tied to a named gate in §5.6.7/§5.6.8.

---

*End of PLAN.md — Sections 1–6 complete.*
