"""Corpus planning: tier sizes, role mix, rule assignment and path layout.

Pure seed-driven planning: the same ``(seed, tier, language)`` triple always
produces the same sorted file plan (Contract 2 §1 determinism; FR-1, FR-4).
The mix semantics recorded in ``mix_tolerance`` are:

- filler / pattern-rich / defect targets 60/30/10 percent of all files with a
  +/-3 percentage-point tolerance band, where the 30% pattern-rich target is
  tallied over ``pattern_rich`` + ``escalation`` files together; and
- escalation files are ~10% of that pattern-rich bucket and carry their own
  role, so they are tallied separately from plain pattern-rich files.
"""

from dataclasses import dataclass

TIER_FILE_COUNTS = {"S": 100, "M": 1000, "L": 10000}
LANGUAGES = ("typescript_node", "python")

RULE_CYCLE = ("INV-002", "TTL-001", "NS-003", "RACE-004")
ESCALATION_REASON_CYCLE = (
    "dynamic_construction",
    "wrapper_depth_exceeded",
    "unresolvable_expression",
    "unsupported_syntax",
)
DEFECT_EXPECTED_TIER = {
    "INV-002": "STATIC_INFERENCE",
    "TTL-001": "DETERMINISTIC_FACT",
    "NS-003": "STATIC_INFERENCE",
    "RACE-004": "DETERMINISTIC_FACT",
}
ESCALATION_EXPECTED_LABEL = {
    "wrapper_depth_exceeded": "MODEL_HYPOTHESIS",
    "dynamic_construction": "UNKNOWN",
    "unresolvable_expression": "UNKNOWN",
    "unsupported_syntax": "UNKNOWN",
}

PATTERN_KINDS_BY_LANGUAGE = {
    "typescript_node": (
        "pipeline",
        "lua_script",
        "pubsub",
        "one_hop_wrapper",
        "template_composition",
        "tsx_component",
    ),
    "python": (
        "pipeline",
        "lua_script",
        "pubsub",
        "one_hop_wrapper",
        "fstring_composition",
    ),
}

MIX_TARGETS_PCT = {"filler": 60, "pattern_rich": 30, "defect": 10}
MIX_TOLERANCE_BAND_PCT = 3
ESCALATION_TARGET_PCT_OF_PATTERN_RICH = 10

# Role assignment is a pure function of the file index modulo 100, so every
# tier reproduces the 60/27/3/10 shape per hundred files exactly.
_FILLER_SLOTS = range(60)
_PATTERN_RICH_SLOTS = range(60, 87)
_ESCALATION_SLOTS = range(87, 90)


@dataclass(frozen=True)
class FilePlan:
    """One planned corpus file with its role and embedded-construct kind."""

    path: str
    role: str
    pattern_kind: str
    rule_id: str | None
    reason_code: str | None


def role_for_index(index: int) -> str:
    """Map a file index onto its role so each 100-file block is 60/27/3/10."""
    position = index % 100
    if position in _FILLER_SLOTS:
        return "filler"
    if position in _PATTERN_RICH_SLOTS:
        return "pattern_rich"
    if position in _ESCALATION_SLOTS:
        return "escalation"
    return "defect"


def plan_corpus(seed: int, tier: str, language: str) -> list[FilePlan]:
    """Build the sorted, deterministic file plan for one corpus run."""
    total_files = TIER_FILE_COUNTS[tier]
    pattern_kinds = PATTERN_KINDS_BY_LANGUAGE[language]
    plans: list[FilePlan] = []
    role_ordinals = {"filler": 0, "pattern_rich": 0, "escalation": 0, "defect": 0}
    for index in range(total_files):
        role = role_for_index(index)
        ordinal = role_ordinals[role]
        role_ordinals[role] += 1
        if role == "pattern_rich":
            pattern_kind = pattern_kinds[ordinal % len(pattern_kinds)]
        else:
            pattern_kind = ""
        rule_id = RULE_CYCLE[ordinal % len(RULE_CYCLE)] if role == "defect" else None
        reason_code = (
            ESCALATION_REASON_CYCLE[ordinal % len(ESCALATION_REASON_CYCLE)]
            if role == "escalation"
            else None
        )
        path = _file_path(language, index, role, pattern_kind)
        plans.append(
            FilePlan(
                path=path,
                role=role,
                pattern_kind=pattern_kind,
                rule_id=rule_id,
                reason_code=reason_code,
            )
        )
    plans.sort(key=lambda plan: plan.path)
    return plans


def _file_path(language: str, index: int, role: str, pattern_kind: str) -> str:
    """Deterministic tree path; the index keeps every path unique."""
    module_number = index // 50
    if language == "typescript_node":
        prefix = f"src/module_{module_number:03d}"
        if role == "pattern_rich" and pattern_kind == "tsx_component":
            return f"{prefix}/panel_{index:05d}.tsx"
        if role == "filler":
            return f"{prefix}/store_{index:05d}.ts"
        if role == "pattern_rich":
            return f"{prefix}/service_{index:05d}.ts"
        if role == "defect":
            return f"{prefix}/handler_{index:05d}.ts"
        return f"{prefix}/resolver_{index:05d}.ts"
    prefix = f"pkg/module_{module_number:03d}"
    if role == "filler":
        return f"{prefix}/store_{index:05d}.py"
    if role == "pattern_rich":
        return f"{prefix}/service_{index:05d}.py"
    if role == "defect":
        return f"{prefix}/handler_{index:05d}.py"
    return f"{prefix}/resolver_{index:05d}.py"
