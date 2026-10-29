"""AC-3 (FR-4): tier-L mix within the manifest-recorded tolerance; defect floors."""

import json
from collections import Counter
from pathlib import Path

MANIFEST_PATH = Path("evaltools/corpus/injection-manifest.json")
MVP_RULE_IDS = ("INV-002", "TTL-001", "NS-003", "RACE-004")
MIN_DEFECTS_PER_RULE_AT_TIER_L = 25
MIN_ESCALATION_CASES = 10


def test_tier_l_file_mix_within_recorded_tolerance() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["tier"] == "L"
    tolerance = manifest["mix_tolerance"]
    role_counts = Counter(file_entry["role"] for file_entry in manifest["files"])
    total_files = sum(role_counts.values())
    targets = tolerance["role_targets_pct"]
    band = tolerance["tolerance_band_pct"]
    # escalation files are a separate role carved from the pattern-rich bucket,
    # per the recorded bucket note.
    pattern_rich_bucket = role_counts["pattern_rich"] + role_counts["escalation"]
    observed_pct = {
        "filler": role_counts["filler"] * 100.0 / total_files,
        "pattern_rich": pattern_rich_bucket * 100.0 / total_files,
        "defect": role_counts["defect"] * 100.0 / total_files,
    }
    for role, target_pct in targets.items():
        assert abs(observed_pct[role] - target_pct) <= band, (
            f"role {role}: observed {observed_pct[role]:.2f}% outside the "
            f"recorded target {target_pct}% ± {band} points"
        )
    escalation_share_of_pattern_rich = (
        role_counts["escalation"] * 100.0 / pattern_rich_bucket
    )
    escalation_target = tolerance["escalation_target_pct_of_pattern_rich"]
    assert abs(escalation_share_of_pattern_rich - escalation_target) <= band, (
        f"escalation share {escalation_share_of_pattern_rich:.2f}% outside the "
        f"recorded target {escalation_target}% ± {band} points"
    )


def test_tier_l_has_at_least_25_defects_per_mvp_rule() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    rule_counts = Counter(defect["rule_id"] for defect in manifest["planted_defects"])
    for rule_id in MVP_RULE_IDS:
        assert rule_counts[rule_id] >= MIN_DEFECTS_PER_RULE_AT_TIER_L, (
            f"rule {rule_id} has {rule_counts[rule_id]} planted defects, below "
            f"the {MIN_DEFECTS_PER_RULE_AT_TIER_L} minimum at tier L"
        )


def test_tier_l_has_at_least_10_escalation_cases() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert len(manifest["escalation_cases"]) >= MIN_ESCALATION_CASES
    # Every escalation case expects an UNKNOWN/MODEL_HYPOTHESIS outcome with a
    # reason code aligned with Contract 1 §5.2's enum.
    for escalation_case in manifest["escalation_cases"]:
        assert escalation_case["expected"] in ("UNKNOWN", "MODEL_HYPOTHESIS")
