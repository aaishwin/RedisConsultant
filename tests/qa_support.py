"""Shared helpers for the Phase-1 qa fixture suite (owner: qa).

Not collected by pytest (module name lacks the ``test_`` prefix). Both the
test modules (via ``conftest.py``) and the fixture runner
(``tests/run_phase1_fixtures.py``) import the drop counter, fixture sources
and label-audit helpers from here so the recorded evidence in
``results/phase1-fixtures.json`` is produced by the same code the tests
execute (Contract 2 §3.10: the verdict is computed, never hand-asserted).
"""

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKOUT_ROOT = REPO_ROOT / "corpora" / "upstream" / "bullmq"
LABELS_PATH = REPO_ROOT / "evaltools" / "exp2" / "labels.json"
RESULTS_DIR = REPO_ROOT / "results"
PINNED_BULLMQ_SHA = "f42514c3d716dc81c2bbc65b883c9dc545fcb56d"

# Sentinel secrets planted in fixture connection config (AC-16, NFR-4). Each
# sentinel is a unique fake value assembled from two fragments so no scanner
# (or human) can mistake it for a real credential; a leak can only come from
# the fixture, never from unrelated repository text.
SENTINEL_CONFIG_PREFIX = "sentinel-pw-"
SENTINEL_CONFIG_SUFFIX = "7f3a9c41be2d"
SENTINEL_URI_PREFIX = "sentinel-uri-pw-"
SENTINEL_URI_SUFFIX = "b28e1d64"
SENTINEL_CONFIG_PASSWORD = SENTINEL_CONFIG_PREFIX + SENTINEL_CONFIG_SUFFIX
SENTINEL_URI_PASSWORD = SENTINEL_URI_PREFIX + SENTINEL_URI_SUFFIX
SENTINELS = (SENTINEL_CONFIG_PASSWORD, SENTINEL_URI_PASSWORD)

# Reason-code enum of Contract 1 §5.1 (UnknownEntry.reason superset).
UNKNOWN_REASON_ENUM = (
    "unsupported_syntax",
    "unresolvable_expression",
    "wrapper_depth_exceeded",
    "dynamic_construction",
    "node_budget_exceeded",
    "file_too_large",
    "parse_error",
)

EPISTEMIC_TIERS = (
    "DETERMINISTIC_FACT",
    "STATIC_INFERENCE",
    "MODEL_HYPOTHESIS",
    "RUNTIME_OBSERVATION",
    "VERIFIED_OUTCOME",
    "UNKNOWN",
)

# --------------------------------------------------------------- fixture set
# Hermetic Phase-1 fixture corpus: every source is an in-memory string, so the
# suite writes nothing outside pytest tmp paths (ADR-106 posture for tests).

_DIRECT_CONSTRUCTION_TS = (
    'import Redis from "ioredis";\n'
    'const client = new Redis({ host: "h", port: 6379 });\n'
    'export function read() { return client.get("k"); }\n'
)

_ONE_HOP_WRAPPER_TS = (
    'import Redis from "ioredis";\n'
    'const base = new Redis({ host: "h" });\n'
    "const alias = base;\n"
    'export function read() { return alias.get("k"); }\n'
)

# R3 (factory_return, DEPTH 1 + inner R2 DEPTH 1) over an R2-injected field:
# the deepest chain the five §3.4 rules resolve to a concrete row (DEPTH 2).
_TWO_LAYER_CHAIN_TS = (
    "export class Service {\n"
    "  private client: Redis;\n"
    "  constructor(client: Redis) {\n"
    "    this.client = client;\n"
    "  }\n"
    "  getClient() { return this.client; }\n"
    '  read() { return this.getClient().get("k"); }\n'
    "}\n"
)

_DEPTH_THREE_WRAPPER_TS = (
    'import Redis from "ioredis";\n'
    'const base = new Redis({ host: "h" });\n'
    "const firstWrapper = new Wrap1(base);\n"
    "const secondWrapper = new Wrap2(firstWrapper);\n"
    "const thirdWrapper = new Wrap3(secondWrapper);\n"
    'export function read() { return thirdWrapper.get("k"); }\n'
)

_DYNAMIC_KEY_CONCAT_TS = (
    'import Redis from "ioredis";\n'
    'const client = new Redis({ host: "h" });\n'
    "export function read(keySuffix: string) {"
    ' return client.set("prefix:" + keySuffix, "v");'
    " }\n"
)

_UNSUPPORTED_SYNTAX_PY = "x = 1\n"

_PARSE_ERROR_TS = "function ( { class ???\n"

_R1_FIELD_TS = (
    'import Redis from "ioredis";\n'
    "export class Store {\n"
    '  private client = new Redis({ host: "h" });\n'
    '  read() { return this.client.get("k"); }\n'
    "}\n"
)

_R2_INJECTION_TS = (
    "export class Service {\n"
    "  private client: Redis;\n"
    "  constructor(client: Redis) {\n"
    "    this.client = client;\n"
    "  }\n"
    '  read() { return this.client.get("k"); }\n'
    "}\n"
)

_R3_FACTORY_TS = (
    'import Redis from "ioredis";\n'
    "function makeClient() {\n"
    '  return new Redis({ host: "h" });\n'
    "}\n"
    'export function read() { return makeClient().get("k"); }\n'
)

_R3_FACTORY_LOCAL_TS = (
    'import Redis from "ioredis";\n'
    "function makeClient() {\n"
    '  return new Redis({ host: "h" });\n'
    "}\n"
    "const boundClient = makeClient();\n"
    'export function read() { return boundClient.get("k"); }\n'
)

_R4_REQUIRE_DIRECT_TS = (
    'const requiredClient = new (require("ioredis"))({ host: "h" });\n'
    'export function read() { return requiredClient.get("k"); }\n'
)

_R4_REQUIRE_ALIAS_TS = (
    'const Redis = require("ioredis");\n'
    'const constructedClient = new Redis({ host: "h" });\n'
    'export function read() { return constructedClient.get("k"); }\n'
)

_R5_NEGATIVE_TS = (
    "export function read(labelsByKey: Map<string, string>) {"
    ' return labelsByKey.get("k");'
    " }\n"
)

_SENTINEL_SECRETS_TS = (
    'import Redis from "ioredis";\n'
    'const client = new Redis({ host: "h", password: "'
    + SENTINEL_CONFIG_PASSWORD
    + '" });\n'
    'const uriClient = new Redis("redis://admin:'
    + SENTINEL_URI_PASSWORD
    + '@h:6379");\n'
    'export function read() { return client.get("k"); }\n'
)

_ALL_FOURTEEN_KINDS_TS = (
    'import Redis from "ioredis";\n'
    "export class S {\n"
    '  private client = new Redis({ host: "h", password: "'
    + SENTINEL_CONFIG_PASSWORD
    + '" });\n'
    "  async read(keyName: string) {\n"
    '    await this.client.set("ns:" + keyName, "v", "EX", 60);\n'
    "    return this.client.get(keyName);\n"
    "  }\n"
    "}\n"
    "export function helper() {\n"
    "  const helperClient = new Redis();\n"
    '  helperClient.expire("k", 300);\n'
    "  return helperClient;\n"
    "}\n"
)

GRAMMAR_MATRIX_SOURCES: dict[str, str] = {
    "plain.ts": "const answer: number = 42;\n",
    "plain.tsx": 'export const node = <div className="k">{"v"}</div>;\n',
    "plain.js": "const answer = 42;\n",
    "plain.mts": "const answer: number = 42;\n",
    "plain.cts": "const answer: number = 42;\n",
    "plain.jsx": 'export const node = <div className="k" />;\n',
    "plain.mjs": "const answer = 42;\n",
    "plain.cjs": "const answer = 42;\n",
}

PHASE1_FIXTURE_SOURCES: dict[str, str] = {
    "plain.ts": GRAMMAR_MATRIX_SOURCES["plain.ts"],
    "plain.tsx": GRAMMAR_MATRIX_SOURCES["plain.tsx"],
    "plain.js": GRAMMAR_MATRIX_SOURCES["plain.js"],
    "direct_construction.ts": _DIRECT_CONSTRUCTION_TS,
    "one_hop_wrapper.ts": _ONE_HOP_WRAPPER_TS,
    "two_layer_chain.ts": _TWO_LAYER_CHAIN_TS,
    "depth_three_wrapper.ts": _DEPTH_THREE_WRAPPER_TS,
    "dynamic_key_concat.ts": _DYNAMIC_KEY_CONCAT_TS,
    "unsupported_syntax.py": _UNSUPPORTED_SYNTAX_PY,
    "parse_error.ts": _PARSE_ERROR_TS,
    "sentinel_secrets.ts": _SENTINEL_SECRETS_TS,
    "all_fourteen_kinds.ts": _ALL_FOURTEEN_KINDS_TS,
    "r1_field.ts": _R1_FIELD_TS,
    "r2_injection.ts": _R2_INJECTION_TS,
    "r3_factory.ts": _R3_FACTORY_TS,
    "r3_factory_local.ts": _R3_FACTORY_LOCAL_TS,
    "r4_require_direct.ts": _R4_REQUIRE_DIRECT_TS,
    "r4_require_alias.ts": _R4_REQUIRE_ALIAS_TS,
    "r5_negative.ts": _R5_NEGATIVE_TS,
}

RESOLUTION_RULE_FIXTURES: dict[str, str] = {
    "r1_field.ts": _R1_FIELD_TS,
    "r2_injection.ts": _R2_INJECTION_TS,
    "r3_factory.ts": _R3_FACTORY_TS,
    "r3_factory_local.ts": _R3_FACTORY_LOCAL_TS,
    "r4_require_direct.ts": _R4_REQUIRE_DIRECT_TS,
    "r4_require_alias.ts": _R4_REQUIRE_ALIAS_TS,
    "r5_negative.ts": _R5_NEGATIVE_TS,
}

ESCALATION_FIXTURE_NAMES = (
    "depth_three_wrapper.ts",
    "dynamic_key_concat.ts",
    "unsupported_syntax.py",
    "parse_error.ts",
)


def oversized_source_bytes() -> bytes:
    """Return a >1 MB TypeScript source (over the parse cap of §3.3)."""
    return b"const filler = 1;\n" * 70_000  # 1,190,000 bytes


def deep_ast_source_bytes() -> bytes:
    """Return a <1 MB source whose tree exceeds the 500,000-node budget.

    ``a&&a&&…`` chains: one binary node plus one identifier node per
    repetition ≈ 2 nodes per 3 bytes, so ~300k identifiers produce ~600k
    tree-sitter nodes inside the 1 MB size cap.
    """
    return b"a" + b"&&a" * 299_999


def checkout_present() -> bool:
    """True when the pinned bullmq checkout is available locally (read-only)."""
    return (CHECKOUT_ROOT / "src" / "classes" / "redis-connection.ts").is_file()


def load_labels() -> list[dict[str, Any]]:
    """Load the frozen EXP-2 label set (byte-frozen at sha256 82d3307f…)."""
    return json.loads(LABELS_PATH.read_text(encoding="utf-8"))["entries"]


# Re-exported so run_phase1_fixtures keeps importing audit_labels from here.
from qa_label_audit import audit_labels  # noqa: E402, F401  (cycle-safe re-export)
