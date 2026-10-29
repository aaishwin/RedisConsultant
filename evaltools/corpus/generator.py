"""Corpus generation orchestration: plan -> emit tree -> manifests.

Bounded memory: each file's lines are built, hashed, written and discarded one
at a time; only path/hash/role records (a few MB at tier L) stay in memory.
The run self-checks its own ground truth before writing any manifest: the
count invariant, the role mix against the recorded tolerance, the per-rule
defect minimum and the escalation minimum all fail the run when violated,
because a manifest that lies about its corpus is worse than no corpus.
"""

import hashlib
from pathlib import Path

from evaltools.corpus import content_py, content_ts
from evaltools.corpus.manifests import (
    FileRecord,
    build_checksum_manifest,
    build_commit_series,
    build_injection_manifest,
    compute_tree_sha256,
)
from evaltools.corpus.model import (
    DEFECT_EXPECTED_TIER,
    ESCALATION_TARGET_PCT_OF_PATTERN_RICH,
    LANGUAGES,
    MIX_TARGETS_PCT,
    MIX_TOLERANCE_BAND_PCT,
    plan_corpus,
)
from evaltools.gate_evidence import require_known_enum, write_result_json

MIN_DEFECTS_PER_RULE_TIER_L = 25
MIN_ESCALATION_CASES_TIER_L = 10


def generate_corpus(
    seed: int, tier: str, language: str, out_dir: Path
) -> dict[str, object]:
    """Generate one corpus tree plus its manifests; returns run statistics."""
    require_known_enum(tier, ("S", "M", "L"), "generator", "tier")
    require_known_enum(language, LANGUAGES, "generator", "language")
    build_file = (
        content_ts.build_ts_file
        if language == "typescript_node"
        else content_py.build_py_file
    )
    plans = plan_corpus(seed, tier, language)
    language_dir = out_dir / language
    corpus_dir = language_dir / "corpus"
    checksum_rows: list[dict[str, object]] = []
    file_records: list[FileRecord] = []
    for plan in plans:
        content = build_file(
            plan.role,
            plan.pattern_kind,
            plan.rule_id,
            plan.reason_code,
            seed,
            plan.path,
        )
        encoded = ("\n".join(content.lines) + "\n").encode()
        target = corpus_dir / plan.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        checksum_rows.append({
            "path": plan.path,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
        })
        file_records.append(
            FileRecord(
                path=plan.path,
                role=plan.role,
                defects=content.defects,
                escalations=content.escalations,
            )
        )
    checksum_rows.sort(key=lambda row: str(row["path"]))
    injection_manifest = build_injection_manifest(seed, tier, language, file_records)
    checksum_manifest = build_checksum_manifest(seed, tier, language, checksum_rows)
    _validate_run_invariants(injection_manifest, tier)
    write_result_json(language_dir / "injection-manifest.json", injection_manifest)
    write_result_json(language_dir / "checksum-manifest.json", checksum_manifest)
    if tier == "L":
        commit_series = build_commit_series(
            seed, tier, language, [str(row["path"]) for row in checksum_rows]
        )
        write_result_json(language_dir / "commit-series.json", commit_series)
    return {
        "seed": seed,
        "tier": tier,
        "language": language,
        "file_count": len(checksum_rows),
        "tree_sha256": compute_tree_sha256(checksum_rows),
        "manifests_dir": str(language_dir),
    }


def _validate_run_invariants(injection_manifest: dict[str, object], tier: str) -> None:
    """Fail the run unless the manifest's own claims hold (count invariant)."""
    files = injection_manifest["files"]
    defects = injection_manifest["planted_defects"]
    escalations = injection_manifest["escalation_cases"]
    assert (
        isinstance(files, list)
        and isinstance(defects, list)
        and isinstance(escalations, list)
    )
    total_files = len(files)
    role_counts = {"filler": 0, "pattern_rich": 0, "escalation": 0, "defect": 0}
    for entry in files:
        assert isinstance(entry, dict)
        role = str(entry["role"])
        role_counts[role] += 1
    _validate_mix(role_counts, total_files)
    rule_counts: dict[str, int] = dict.fromkeys(DEFECT_EXPECTED_TIER, 0)
    for defect in defects:
        assert isinstance(defect, dict)
        rule_counts[str(defect["rule_id"])] += 1
    if len(defects) != role_counts["defect"]:
        raise ValueError(
            f"count invariant violated: {len(defects)} planted defects but "
            f"{role_counts['defect']} defect files"
        )
    if len(escalations) != role_counts["escalation"]:
        raise ValueError(
            f"count invariant violated: {len(escalations)} escalation cases but "
            f"{role_counts['escalation']} escalation files"
        )
    if tier == "L":
        under_minima = {
            rule_id: count
            for rule_id, count in rule_counts.items()
            if count < MIN_DEFECTS_PER_RULE_TIER_L
        }
        if under_minima:
            raise ValueError(
                f"tier-L defect minima unmet (>=25 per rule): {under_minima}"
            )
        if len(escalations) < MIN_ESCALATION_CASES_TIER_L:
            raise ValueError(
                f"tier-L escalation minimum unmet: {len(escalations)} < "
                f"{MIN_ESCALATION_CASES_TIER_L}"
            )


def _validate_mix(role_counts: dict[str, int], total_files: int) -> None:
    """Check the role mix against the tolerance recorded in the manifest."""
    if total_files == 0:
        raise ValueError("generated corpus is empty")
    pattern_rich_bucket = role_counts["pattern_rich"] + role_counts["escalation"]
    tallied_percentages = {
        "filler": role_counts["filler"] * 100 / total_files,
        "pattern_rich": pattern_rich_bucket * 100 / total_files,
        "defect": role_counts["defect"] * 100 / total_files,
    }
    for role, target_pct in MIX_TARGETS_PCT.items():
        actual_pct = tallied_percentages[role]
        if abs(actual_pct - target_pct) > MIX_TOLERANCE_BAND_PCT:
            raise ValueError(
                f"role mix outside tolerance for {role!r}: {actual_pct:.2f}% vs "
                f"target {target_pct}% (+/-{MIX_TOLERANCE_BAND_PCT})"
            )
    escalation_pct_of_bucket = (
        role_counts["escalation"] * 100 / pattern_rich_bucket
        if pattern_rich_bucket
        else 0.0
    )
    if abs(escalation_pct_of_bucket - ESCALATION_TARGET_PCT_OF_PATTERN_RICH) > 1.0:
        raise ValueError(
            f"escalation share outside tolerance: {escalation_pct_of_bucket:.2f}%"
            f" of the "
            f"pattern-rich bucket vs target {ESCALATION_TARGET_PCT_OF_PATTERN_RICH}%"
        )
