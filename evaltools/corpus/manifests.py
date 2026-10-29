"""Manifest builders for the synthetic corpus (Contract 2 §3.1-§3.3).

Every manifest is a pure function over the generated corpus records and the
run parameters: no wall-clock fields, sorted arrays, enum values validated
through ``gate_evidence`` before writing so an out-of-contract value fails
fast at the boundary (Contract 2 §1 and §6).
"""

import hashlib
import platform
from dataclasses import dataclass

from evaltools.corpus.content import DefectSpec, EscalationSpec
from evaltools.corpus.model import (
    DEFECT_EXPECTED_TIER,
    ESCALATION_EXPECTED_LABEL,
    ESCALATION_TARGET_PCT_OF_PATTERN_RICH,
    LANGUAGES,
    MIX_TARGETS_PCT,
    MIX_TOLERANCE_BAND_PCT,
)
from evaltools.corpus.prng import derive_int
from evaltools.gate_evidence import SCHEMA_VERSION, require_known_enum

GENERATOR_VERSION = "0.1.0"

CHANGE_KIND_CYCLE = (
    "modified_body",
    "renamed_file",
    "deleted_file",
    "changed_signature",
    "modified_key_template",
    "grammar_relevant_syntax",
    "no_op",
)
CHANGE_KIND_DESCRIPTIONS = {
    "modified_body": (
        "Edit function bodies in {path} without changing signatures or key templates."
    ),
    "deleted_file": "Delete {path}; downstream readers must observe the removal.",
    "changed_signature": "Change a function signature in {path}.",
    "modified_key_template": "Change a cache key template in {path}.",
    "grammar_relevant_syntax": (
        "Introduce grammar-relevant syntax (template literal / TSX) in {path}."
    ),
    "no_op": "Whitespace-only touch to {path}; the parsed tree is unchanged.",
}


@dataclass(frozen=True)
class FileRecord:
    """One emitted file with the ground truth embedded in its bytes."""

    path: str
    role: str
    defects: list[DefectSpec]
    escalations: list[EscalationSpec]


def build_injection_manifest(
    seed: int, tier: str, language: str, file_records: list[FileRecord]
) -> dict[str, object]:
    """Build the ground-truth manifest (Contract 2 §3.1)."""
    require_known_enum(language, LANGUAGES, "injection-manifest.json", "language")
    files: list[dict[str, str]] = []
    planted_defects: list[dict[str, object]] = []
    escalation_cases: list[dict[str, object]] = []
    defect_ordinal = 0
    escalation_ordinal = 0
    for record in sorted(file_records, key=lambda item: item.path):
        require_known_enum(
            record.role,
            ("filler", "pattern_rich", "defect", "escalation"),
            "injection-manifest.json",
            "files[].role",
        )
        files.append({"path": record.path, "role": record.role})
        for defect in record.defects:
            defect_ordinal += 1
            require_known_enum(
                defect.rule_id,
                tuple(DEFECT_EXPECTED_TIER),
                "injection-manifest.json",
                "planted_defects[].rule_id",
            )
            expected_tier = DEFECT_EXPECTED_TIER[defect.rule_id]
            require_known_enum(
                expected_tier,
                tuple(DEFECT_EXPECTED_TIER.values()),
                "injection-manifest.json",
                "planted_defects[].expected_tier",
            )
            planted_defects.append({
                "defect_id": f"D-{defect_ordinal:06d}",
                "rule_id": defect.rule_id,
                "file": record.path,
                "span": dict(defect.span),
                "expected_tier": expected_tier,
            })
        for escalation in record.escalations:
            escalation_ordinal += 1
            require_known_enum(
                escalation.reason_code,
                tuple(ESCALATION_EXPECTED_LABEL),
                "injection-manifest.json",
                "escalation_cases[].reason_code",
            )
            expected_label = ESCALATION_EXPECTED_LABEL[escalation.reason_code]
            require_known_enum(
                expected_label,
                ("UNKNOWN", "MODEL_HYPOTHESIS"),
                "injection-manifest.json",
                "escalation_cases[].expected",
            )
            escalation_cases.append({
                "case_id": f"E-{escalation_ordinal:06d}",
                "expected": expected_label,
                "reason_code": escalation.reason_code,
                "file": record.path,
                "span": dict(escalation.span),
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "tier": tier,
        "language": language,
        "files": files,
        "planted_defects": planted_defects,
        "escalation_cases": escalation_cases,
        "mix_tolerance": build_mix_tolerance(),
    }


def build_mix_tolerance() -> dict[str, object]:
    """The AC-3 60/30/10 tolerance, recorded in the manifest itself."""
    return {
        "role_targets_pct": dict(MIX_TARGETS_PCT),
        "tolerance_band_pct": MIX_TOLERANCE_BAND_PCT,
        "pattern_rich_bucket_note": (
            "The pattern_rich target is tallied over pattern_rich + escalation files "
            "together; escalation files are a separate role carved from that bucket."
        ),
        "escalation_target_pct_of_pattern_rich": ESCALATION_TARGET_PCT_OF_PATTERN_RICH,
    }


def build_checksum_manifest(
    seed: int, tier: str, language: str, checksum_rows: list[dict[str, object]]
) -> dict[str, object]:
    """Build the byte-identical repetition oracle (Contract 2 §3.2)."""
    require_known_enum(language, LANGUAGES, "checksum-manifest.json", "language")
    sorted_rows = sorted(checksum_rows, key=lambda row: str(row["path"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "tier": tier,
        "language": language,
        "toolchain": {
            "python_version": platform.python_version(),
            "generator_version": GENERATOR_VERSION,
        },
        "files": sorted_rows,
        "tree_sha256": compute_tree_sha256(sorted_rows),
    }


def compute_tree_sha256(sorted_checksum_rows: list[dict[str, object]]) -> str:
    """sha256 over the newline-joined `sha256  path` lines in sorted order."""
    digest_input = "\n".join(
        f"{row['sha256']}  {row['path']}" for row in sorted_checksum_rows
    ).encode()
    return hashlib.sha256(digest_input).hexdigest()


def build_commit_series(
    seed: int, tier: str, language: str, sorted_paths: list[str]
) -> dict[str, object]:
    """Build the scripted 20-entry commit series (Contract 2 §3.3, FR-5)."""
    require_known_enum(language, LANGUAGES, "commit-series.json", "language")

    commits: list[dict[str, object]] = []
    for commit_index in range(1, 21):
        change_kind = CHANGE_KIND_CYCLE[(commit_index - 1) % len(CHANGE_KIND_CYCLE)]
        victim_path = sorted_paths[
            derive_int(seed, f"commit-series:{commit_index}", 0, len(sorted_paths))
        ]
        if change_kind == "renamed_file":
            new_path = _renamed_path(victim_path)
            commit_files: list[dict[str, str | None]] = [
                {
                    "path": new_path,
                    "prior_path": victim_path,
                    "description": (
                        f"Rename {victim_path} to {new_path} (scripted commit"
                        f" {commit_index})."
                    ),
                }
            ]
        else:
            commit_files = [
                {
                    "path": victim_path,
                    "prior_path": None,
                    "description": CHANGE_KIND_DESCRIPTIONS[change_kind].format(
                        path=victim_path
                    ),
                }
            ]
        require_known_enum(
            change_kind,
            CHANGE_KIND_CYCLE,
            "commit-series.json",
            "commits[].change_kind",
        )
        commits.append({
            "commit_index": commit_index,
            "change_kind": change_kind,
            "files": commit_files,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "seed": seed,
        "tier": tier,
        "language": language,
        "commits": commits,
    }


def _renamed_path(original_path: str) -> str:
    stem, separator, extension = original_path.rpartition(".")
    if not separator:
        return f"{original_path}.renamed"
    return f"{stem}.renamed.{extension}"
