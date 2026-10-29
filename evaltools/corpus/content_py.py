"""Python synthetic-file emitter (pure: seed + stream -> lines + spans).

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
from evaltools.corpus.content_py_blocks import (
    _PY_PATTERN_BLOCK_BUILDERS,
    _py_cache_aside_block,
)
from evaltools.corpus.content_py_defects import (
    _py_missing_invalidation_block,
    _py_missing_ttl_block,
    _py_namespace_mismatch_block,
    _py_read_modify_write_block,
)
from evaltools.corpus.content_py_escalation import (
    _py_dynamic_construction_block,
    _py_unresolvable_expression_block,
    _py_unsupported_syntax_block,
    _py_wrapper_depth_block,
)
from evaltools.corpus.prng import derive_int, derive_pick

PATTERN_KINDS = (
    "pipeline",
    "lua_script",
    "pubsub",
    "one_hop_wrapper",
    "fstring_composition",
)


def build_py_file(
    role: str,
    pattern_kind: str,
    rule_id: str | None,
    reason_code: str | None,
    seed: int,
    stream: str,
) -> FileContent:
    """Emit one Python file for the given plan."""
    if role == "filler":
        return _py_filler_file(seed, stream)
    if role == "pattern_rich":
        return _py_pattern_file(pattern_kind, seed, stream)
    if role == "defect":
        return _py_defect_file(rule_id, seed, stream)
    return _py_escalation_file(reason_code, seed, stream)


def _py_file_header(entity: str) -> list[str]:
    """Docstring, imports, constants, database stub and Redis client."""
    return [
        f'"""Synthetic service module: cache-aside helpers for {entity} records."""',
        "",
        "import json",
        "",
        "import redis",
        "",
        "CACHE_TTL_SECONDS = 300",
        "client = redis.Redis.from_url('redis://localhost:6379/0')",
        "",
        "",
        "class RecordDatabase:",
        f"    def load_{entity}(self, record_id: str) -> dict:",
        "        return {",
        "            'id': record_id,",
        f"            'display_name': '{entity}-' + record_id,",
        "            'updated_at': '2026-01-01T00:00:00Z',",
        "        }",
        "",
        f"    def save_{entity}(self, record_id: str, record: dict) -> None:",
        "        return None",
        "",
        "",
        "database = RecordDatabase()",
        "",
    ]


def _py_filler_file(seed: int, stream: str) -> FileContent:
    entity = derive_pick(seed, f"{stream}:entity", ENTITIES)
    lines = _py_file_header(entity)
    for ordinal in range(7):
        suffix = ordinal * 1000 + derive_int(seed, f"{stream}:block:{ordinal}", 0, 1000)
        lines.extend(_py_cache_aside_block(entity, suffix))
    return FileContent(lines=lines, defects=[], escalations=[])


def _py_pattern_file(pattern_kind: str, seed: int, stream: str) -> FileContent:
    entity = derive_pick(seed, f"{stream}:entity", ENTITIES)
    block_builder = _PY_PATTERN_BLOCK_BUILDERS[pattern_kind]
    lines = _py_file_header(entity)
    for ordinal in range(2):
        suffix = ordinal * 1000 + derive_int(
            seed, f"{stream}:pattern:{ordinal}", 0, 1000
        )
        lines.extend(block_builder(entity, suffix))
    for ordinal in range(4):
        suffix = ordinal * 1000 + derive_int(
            seed, f"{stream}:neutral:{ordinal}", 0, 1000
        )
        lines.extend(_py_cache_aside_block(entity, suffix))
    return FileContent(lines=lines, defects=[], escalations=[])


def _py_defect_file(rule_id: str | None, seed: int, stream: str) -> FileContent:
    if rule_id is None:
        raise ValueError("defect file plan is missing rule_id")
    entity = derive_pick(seed, f"{stream}:entity", ENTITIES)
    lines = _py_file_header(entity)
    defects: list[DefectSpec] = []
    defect_block_builders: dict[
        str, Callable[[str, int, str], tuple[list[str], list[DefectSpec]]]
    ] = {
        "INV-002": _py_missing_invalidation_block,
        "TTL-001": _py_missing_ttl_block,
        "NS-003": _py_namespace_mismatch_block,
        "RACE-004": _py_read_modify_write_block,
    }
    if rule_id not in defect_block_builders:
        raise ValueError(f"unknown defect rule_id {rule_id!r} for Python emitter")
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
        lines.extend(_py_cache_aside_block(entity, suffix))
    return FileContent(lines=lines, defects=defects, escalations=[])


def _py_escalation_file(reason_code: str | None, seed: int, stream: str) -> FileContent:
    if reason_code is None:
        raise ValueError("escalation file plan is missing reason_code")
    entity = derive_pick(seed, f"{stream}:entity", ENTITIES)
    lines = _py_file_header(entity)
    escalations: list[EscalationSpec] = []
    escalation_block_builders: dict[
        str, Callable[[str, int, str], tuple[list[str], list[EscalationSpec]]]
    ] = {
        "wrapper_depth_exceeded": _py_wrapper_depth_block,
        "dynamic_construction": _py_dynamic_construction_block,
        "unresolvable_expression": _py_unresolvable_expression_block,
        "unsupported_syntax": _py_unsupported_syntax_block,
    }
    if reason_code not in escalation_block_builders:
        raise ValueError(
            f"unknown escalation reason_code {reason_code!r} for Python emitter"
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
        lines.extend(_py_cache_aside_block(entity, suffix))
    return FileContent(lines=lines, defects=[], escalations=escalations)
