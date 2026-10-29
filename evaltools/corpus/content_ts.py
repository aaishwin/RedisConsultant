"""TypeScript/Node synthetic-file emitter (pure: seed + stream -> lines + spans).

Every builder is a pure function over its arguments: no clock, no randomness,
no I/O. All content decisions come from the seed-derived PRF so the same
``(seed, stream)`` pair always yields byte-identical lines (FR-3).

Special blocks (defects, escalations) locate their spans inside their own
block; the file assembler then shifts them onto file-absolute lines with
:func:`evaltools.corpus.content.shift_span`, so a manifest span always points
at the construct in the emitted bytes.
"""

from collections.abc import Callable

from evaltools.corpus.content import (
    ENTITIES,
    DefectSpec,
    EscalationSpec,
    FileContent,
    shift_span,
)
from evaltools.corpus.content_ts_blocks import (
    _TS_PATTERN_BLOCK_BUILDERS,
    _ts_cache_aside_block,
)
from evaltools.corpus.content_ts_defects import (
    _ts_missing_invalidation_block,
    _ts_missing_ttl_block,
    _ts_namespace_mismatch_block,
    _ts_read_modify_write_block,
)
from evaltools.corpus.content_ts_escalation import (
    _ts_dynamic_construction_block,
    _ts_unresolvable_expression_block,
    _ts_unsupported_syntax_block,
    _ts_wrapper_depth_block,
)
from evaltools.corpus.prng import derive_int, derive_pick

PATTERN_KINDS = (
    "pipeline",
    "lua_script",
    "pubsub",
    "one_hop_wrapper",
    "template_composition",
    "tsx_component",
)


def build_ts_file(
    role: str,
    pattern_kind: str,
    rule_id: str | None,
    reason_code: str | None,
    seed: int,
    stream: str,
) -> FileContent:
    """Emit one TypeScript/Node file for the given plan."""
    if role == "filler":
        return _ts_filler_file(seed, stream)
    if role == "pattern_rich":
        if pattern_kind == "tsx_component":
            return _ts_tsx_file(seed, stream)
        return _ts_pattern_file(pattern_kind, seed, stream)
    if role == "defect":
        return _ts_defect_file(rule_id, seed, stream)
    return _ts_escalation_file(reason_code, seed, stream)


def _ts_file_header(entity: str) -> list[str]:
    """Imports, constants, record interface, database stub and Redis client."""
    capitalized = entity.capitalize()
    return [
        f"// Synthetic service module: cache-aside helpers for {entity} records.",
        'import { createClient } from "redis";',
        "",
        "const CACHE_TTL_SECONDS = 300;",
        "",
        f"export interface {capitalized}Record {{",
        "  id: string;",
        "  displayName: string;",
        "  updatedAt: string;",
        "}",
        "",
        "class RecordDatabase {",
        f"  async load{capitalized}(id: string): Promise<{capitalized}Record> {{",
        (
            f"    return {{ id, displayName: `{entity}-${{id}}`, updatedAt: "
            f'"2026-01-01T00:00:00Z" }};'
        ),
        "  }",
        "",
        (
            f"  async save{capitalized}(id: string, record: {capitalized}Record):"
            f" Promise<void> {{"
        ),
        "    return undefined;",
        "  }",
        "}",
        "",
        "const database = new RecordDatabase();",
        (
            'const client = createClient({ url: process.env.REDIS_URL ?? "redis://localhost:6379"'
            " });"
        ),
        "",
    ]


def _ts_filler_file(seed: int, stream: str) -> FileContent:
    entity = derive_pick(seed, f"{stream}:entity", ENTITIES)
    lines = _ts_file_header(entity)
    for ordinal in range(7):
        suffix = ordinal * 1000 + derive_int(seed, f"{stream}:block:{ordinal}", 0, 1000)
        lines.extend(_ts_cache_aside_block(entity, suffix))
    return FileContent(lines=lines, defects=[], escalations=[])


def _ts_pattern_file(pattern_kind: str, seed: int, stream: str) -> FileContent:
    entity = derive_pick(seed, f"{stream}:entity", ENTITIES)
    block_builder = _TS_PATTERN_BLOCK_BUILDERS[pattern_kind]
    lines = _ts_file_header(entity)
    for ordinal in range(2):
        suffix = ordinal * 1000 + derive_int(
            seed, f"{stream}:pattern:{ordinal}", 0, 1000
        )
        lines.extend(block_builder(entity, suffix))
    for ordinal in range(4):
        suffix = ordinal * 1000 + derive_int(
            seed, f"{stream}:neutral:{ordinal}", 0, 1000
        )
        lines.extend(_ts_cache_aside_block(entity, suffix))
    return FileContent(lines=lines, defects=[], escalations=[])


def _ts_tsx_file(seed: int, stream: str) -> FileContent:
    entity = derive_pick(seed, f"{stream}:entity", ENTITIES)
    capitalized = entity.capitalize()
    lines = [
        (
            f"// Synthetic UI module: TSX surface over a one-hop cache wrapper for"
            f" {entity} records."
        ),
        'import { useEffect, useState } from "react";',
        'import { createClient } from "redis";',
        "",
        (
            f"export async function fetch{capitalized}Summary(recordId: string):"
            f" Promise<string | null> {{"
        ),
        f"  return client.get(`{entity}:${{recordId}}:summary`);",
        "}",
        "",
        (
            f"export function {capitalized}Panel({{ recordId }}: {{ recordId: string"
            f" }}) {{"
        ),
        "  const [summaryText, setSummaryText] = useState<string | null>(null);",
        "  useEffect(() => {",
        (
            f"    fetch{capitalized}Summary(recordId).then((value) =>"
            f" setSummaryText(value));"
        ),
        "  }, [recordId]);",
        (
            '  return <section className="panel" data-record-id={recordId}>'
            '{summaryText ?? "loading"}</section>;'
        ),
        "}",
        "",
    ]
    for ordinal in range(6):
        suffix = ordinal * 1000 + derive_int(
            seed, f"{stream}:neutral:{ordinal}", 0, 1000
        )
        lines.extend(_ts_cache_aside_block(entity, suffix))
    return FileContent(lines=lines, defects=[], escalations=[])


def _ts_defect_file(rule_id: str | None, seed: int, stream: str) -> FileContent:
    if rule_id is None:
        raise ValueError("defect file plan is missing rule_id")
    entity = derive_pick(seed, f"{stream}:entity", ENTITIES)
    lines = _ts_file_header(entity)
    defects: list[DefectSpec] = []
    defect_block_builders: dict[
        str, Callable[[str, int, str], tuple[list[str], list[DefectSpec]]]
    ] = {
        "INV-002": _ts_missing_invalidation_block,
        "TTL-001": _ts_missing_ttl_block,
        "NS-003": _ts_namespace_mismatch_block,
        "RACE-004": _ts_read_modify_write_block,
    }
    if rule_id not in defect_block_builders:
        raise ValueError(f"unknown defect rule_id {rule_id!r} for TypeScript emitter")
    block, block_defects = defect_block_builders[rule_id](entity, seed, stream)
    line_offset = len(lines)
    lines.extend(block)
    defects.extend(
        DefectSpec(spec.rule_id, shift_span(spec.span, line_offset))
        for spec in block_defects
    )
    for ordinal in range(4):
        suffix = ordinal * 1000 + derive_int(
            seed, f"{stream}:neutral:{ordinal}", 0, 1000
        )
        lines.extend(_ts_cache_aside_block(entity, suffix))
    return FileContent(lines=lines, defects=defects, escalations=[])


def _ts_escalation_file(reason_code: str | None, seed: int, stream: str) -> FileContent:
    if reason_code is None:
        raise ValueError("escalation file plan is missing reason_code")
    entity = derive_pick(seed, f"{stream}:entity", ENTITIES)
    lines = _ts_file_header(entity)
    escalations: list[EscalationSpec] = []
    escalation_block_builders: dict[
        str, Callable[[str, int, str], tuple[list[str], list[EscalationSpec]]]
    ] = {
        "wrapper_depth_exceeded": _ts_wrapper_depth_block,
        "dynamic_construction": _ts_dynamic_construction_block,
        "unresolvable_expression": _ts_unresolvable_expression_block,
        "unsupported_syntax": _ts_unsupported_syntax_block,
    }
    if reason_code not in escalation_block_builders:
        raise ValueError(
            f"unknown escalation reason_code {reason_code!r} for TypeScript emitter"
        )
    block, block_escalations = escalation_block_builders[reason_code](
        entity, seed, stream
    )
    line_offset = len(lines)
    lines.extend(block)
    escalations.extend(
        EscalationSpec(spec.reason_code, shift_span(spec.span, line_offset))
        for spec in block_escalations
    )
    for ordinal in range(4):
        suffix = ordinal * 1000 + derive_int(
            seed, f"{stream}:neutral:{ordinal}", 0, 1000
        )
        lines.extend(_ts_cache_aside_block(entity, suffix))
    return FileContent(lines=lines, defects=[], escalations=escalations)
