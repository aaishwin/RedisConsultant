"""Adjudicated label audit moved out of qa_support.py (style contract rule 8).

Read-only verification of the EXP-2 label fixtures; the helpers it depends on
remain in qa_support and are imported back, so the recorded evidence is still
produced by one implementation.
"""

from dataclasses import dataclass
from typing import Any

from qa_support import CHECKOUT_ROOT, LABELS_PATH, checkout_present, load_labels


@dataclass(frozen=True)
class LabelAuditVerdict:
    """One spot-checked label's adjudication (qa's independent reading)."""

    callsite_id: str
    checked: bool
    verdict: str  # "label_correct" | "label_wrong"
    evidence: str


ADJUDICATED_LABELS: tuple[LabelAuditVerdict, ...] = (
    LabelAuditVerdict(
        "cs-002",
        True,
        "label_correct",
        "src/classes/ioredis-client.ts:91 'return augmentTransaction((client as"
        " any).multi(...args));' "
        "— genuine ioredis multi() forwarded to the raw client through the Proxy"
        " leg; positive label correct.",
    ),
    LabelAuditVerdict(
        "cs-003",
        True,
        "label_correct",
        "src/classes/ioredis-client.ts:126 '(client as any).hset(key, dataOrField,"
        " ...rest)' — raw-client "
        "hset forwarding; positive label correct.",
    ),
    LabelAuditVerdict(
        "cs-004",
        True,
        "label_correct",
        "src/classes/ioredis-client.ts:143 '(client as any).set(' (multiline"
        " through 147) — raw-client set "
        "forwarding; positive label correct.",
    ),
    LabelAuditVerdict(
        "cs-005",
        True,
        "label_correct",
        "src/classes/ioredis-client.ts:167 '(client as any).zrange(key, start,"
        " end, optionsOrStr, ...rest)' — "
        "positive label correct.",
    ),
    LabelAuditVerdict(
        "cs-006",
        True,
        "label_correct",
        'src/classes/ioredis-client.ts:170 "(client as any).zrange(key, start,'
        " end, 'WITHSCORES')\" — positive "
        "label correct.",
    ),
    LabelAuditVerdict(
        "cs-007",
        True,
        "label_correct",
        "src/classes/ioredis-client.ts:172 '(client as any).zrange(key, start,"
        " end)' — positive label correct.",
    ),
    LabelAuditVerdict(
        "cs-016",
        True,
        "label_correct",
        "src/classes/node-redis-client.ts:505 'return new"
        " NodeRedisTransaction(this.raw.multi(), this.scripts);' "
        "— this.raw is the raw node-redis client (field of the adapter class), so"
        " multi() is a genuine Redis "
        "callsite one hop up; positive label correct.",
    ),
    LabelAuditVerdict(
        "cs-001",
        True,
        "label_correct",
        "src/classes/ioredis-client.ts:63 'const cached = proxyCache.get(client);'"
        " — proxyCache is declared "
        "'new WeakMap<object, IRedisClient>()' (line 9): Map/WeakMap API, not"
        " Redis; negative label correct.",
    ),
    LabelAuditVerdict(
        "cs-008",
        True,
        "label_correct",
        "src/classes/ioredis-client.ts:319 'boundCache.set(prop, bound);' —"
        " boundCache is 'new Map<PropertyKey, "
        "any>()' (line 71): Map.set, not Redis; negative label correct.",
    ),
    LabelAuditVerdict(
        "cs-009",
        True,
        "label_correct",
        "src/classes/ioredis-client.ts:350 'proxyCache.set(client, proxy);' —"
        " WeakMap.set, not Redis; negative "
        "label correct.",
    ),
    LabelAuditVerdict(
        "cs-010",
        True,
        "label_correct",
        "src/classes/job.ts:275 'job.id = await job.backend.addJob(jobData,"
        " job.id, {' — backend is an "
        "IQueueBackend abstraction (field declaration line 186), addJob is not a"
        " Redis command; negative "
        "label correct.",
    ),
    LabelAuditVerdict(
        "cs-011",
        True,
        "label_correct",
        "src/classes/job.ts:675 'await this.backend.moveToCompleted(' — backend"
        " abstraction method, not a "
        "Redis command; negative label correct.",
    ),
    LabelAuditVerdict(
        "cs-012",
        True,
        "label_correct",
        "src/classes/lock-manager.ts:60 'id => this.trackedJobs.get(id)?.token' —"
        " trackedJobs is "
        "'new Map<…>' (line 21): Map.get, not Redis; negative label correct.",
    ),
    LabelAuditVerdict(
        "cs-013",
        True,
        "label_correct",
        "src/classes/lock-manager.ts:106 'for (const jobId of"
        " this.trackedJobs.keys()) {' — Map.keys "
        "iterator, not Redis KEYS; negative label correct.",
    ),
)


NEGATIVE_DECLARATION_EVIDENCE: dict[str, tuple[str, str]] = {
    "cs-001": ("src/classes/ioredis-client.ts", "new WeakMap<object, IRedisClient>"),
    "cs-008": ("src/classes/ioredis-client.ts", "new Map<PropertyKey"),
    "cs-009": ("src/classes/ioredis-client.ts", "new WeakMap<object, IRedisClient>"),
    "cs-010": ("src/classes/job.ts", "backend: IQueueBackend"),
    "cs-011": ("src/classes/job.ts", "backend: IQueueBackend"),
    "cs-012": ("src/classes/lock-manager.ts", "new Map<"),
    "cs-013": ("src/classes/lock-manager.ts", "new Map<"),
}


def audit_labels() -> dict[str, Any]:
    """Run the ≥20% EXP-2 label audit against the pinned checkout.

    Returns the Contract 2 §3.10 ``label_audit`` payload. The audit re-verifies,
    mechanically and read-only, every claim encoded in ADJUDICATED_LABELS:
    the labelled line exists and contains the labelled method call, negative
    receivers have their non-Redis declaration in the same file, and the label
    set is still the byte-frozen 52-entry set (sha256 82d3307f…).
    """
    import hashlib

    labels = load_labels()
    labels_sha256 = hashlib.sha256(LABELS_PATH.read_bytes()).hexdigest()
    frozen_sha256 = "82d3307fb46bda1d364e11a122c7501bf79fd3e2bac40e8d80903c59ffbe79ad"
    mismatches: list[str] = []
    checked_ids: list[str] = []
    checked_count = 0
    for adjudication in ADJUDICATED_LABELS:
        matching_labels = [
            entry
            for entry in labels
            if entry["callsite_id"] == adjudication.callsite_id
        ]
        if not matching_labels:
            mismatches.append(f"{adjudication.callsite_id}: not present in labels.json")
            continue
        label = matching_labels[0]
        checked_ids.append(label["callsite_id"])
        if not checkout_present():
            mismatches.append(
                f"{label['callsite_id']}: pinned checkout unavailable; audit not"
                f" executed"
            )
            continue
        source_lines = (
            (CHECKOUT_ROOT / label["file"]).read_text(encoding="utf-8").splitlines()
        )
        start_line = label["span"]["start_line"]
        line_text = (
            source_lines[start_line - 1] if start_line - 1 < len(source_lines) else ""
        )
        method_call_present = (
            f".{label['method']}(" in line_text or f"{label['method']}(" in line_text
        )
        if not method_call_present:
            mismatches.append(
                f"{label['callsite_id']}: labelled method {label['method']} not"
                f" found on line {start_line}"
            )
            continue
        if not label["expected_is_redis_callsite"]:
            declaration_file, declaration_text = NEGATIVE_DECLARATION_EVIDENCE[
                label["callsite_id"]
            ]
            declaration_present = declaration_text in (
                CHECKOUT_ROOT / declaration_file
            ).read_text(encoding="utf-8")
            if not declaration_present:
                mismatches.append(
                    f"{label['callsite_id']}: non-Redis receiver declaration "
                    f"{declaration_text!r} not found in {declaration_file}"
                )
                continue
        checked_count += 1
    return {
        "total_callsites": len(labels),
        "checked_callsite_ids": checked_ids,
        "checked_count": checked_count,
        "min_required": 10,
        "mismatches": mismatches,
        "result": "pass" if not mismatches and checked_count >= 10 else "fail",
        "labels_sha256": labels_sha256,
        "labels_sha256_matches_frozen": labels_sha256 == frozen_sha256,
        "note": (
            "Contract 2 §3.10 says 'total_callsites: 50'; the actual frozen label "
            "set contains 52 entries (38 positive / 14 negative). The real count "
            "is recorded here and the contract-text deviation is flagged instead "
            "of edited (leader decision recorded in the dispatch)."
        ),
    }
