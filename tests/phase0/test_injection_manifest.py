"""AC-1 (FR-1, FR-2): injection manifests for both languages, schema-conformant."""

import json
from pathlib import Path

from evaltools.corpus.generator import generate_corpus
from evaltools.corpus.model import LANGUAGES

COMMITTED_MANIFEST_PATH = Path("evaltools/corpus/injection-manifest.json")
PINNED_SEED = 194406
DEFECT_RULE_IDS = ("INV-002", "TTL-001", "NS-003", "RACE-004")
FILE_ROLES = ("filler", "pattern_rich", "defect", "escalation")
EXPECTED_DEFECT_TIERS = (
    "DETERMINISTIC_FACT",
    "STATIC_INFERENCE",
    "MODEL_HYPOTHESIS",
    "UNKNOWN",
)
ESCALATION_REASON_CODES = (
    "unsupported_syntax",
    "unresolvable_expression",
    "wrapper_depth_exceeded",
    "dynamic_construction",
)


def _assert_manifest_schema_conformant(manifest: dict, language: str) -> None:
    assert manifest["schema_version"] == "eval-schema 0.1.1"
    assert manifest["seed"] == PINNED_SEED
    assert manifest["tier"] in ("S", "M", "L")
    assert manifest["language"] == language
    assert len(manifest["files"]) > 0
    for file_entry in manifest["files"]:
        assert set(file_entry) == {"path", "role"}
        assert file_entry["role"] in FILE_ROLES
    assert len(manifest["planted_defects"]) > 0
    for defect in manifest["planted_defects"]:
        assert set(defect) == {
            "defect_id",
            "rule_id",
            "file",
            "span",
            "expected_tier",
        }
        assert defect["rule_id"] in DEFECT_RULE_IDS
        span = defect["span"]
        assert span["start_line"] >= 1 and span["start_col"] >= 1
        assert span["end_line"] >= span["start_line"]
        assert defect["expected_tier"] in EXPECTED_DEFECT_TIERS
    assert len(manifest["escalation_cases"]) > 0
    for escalation_case in manifest["escalation_cases"]:
        assert escalation_case["expected"] in ("UNKNOWN", "MODEL_HYPOTHESIS")
        assert escalation_case["reason_code"] in ESCALATION_REASON_CODES
        assert escalation_case["file"] and escalation_case["span"]
    assert "mix_tolerance" in manifest


def test_committed_tier_l_typescript_manifest_conforms() -> None:
    manifest = json.loads(COMMITTED_MANIFEST_PATH.read_text(encoding="utf-8"))
    _assert_manifest_schema_conformant(manifest, "typescript_node")
    assert manifest["tier"] == "L"


def test_generator_emits_both_languages_with_injection_manifests(
    tmp_path: Path,
) -> None:
    """FR-2: the same generator run emits TS/Node and Python repos (AC-1)."""
    output_root = tmp_path / "tier-s-both"
    for language in LANGUAGES:
        generate_corpus(PINNED_SEED, "S", language, output_root)
        manifest_path = output_root / language / "injection-manifest.json"
        assert manifest_path.is_file(), f"missing injection manifest for {language}"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _assert_manifest_schema_conformant(manifest, language)
        assert manifest["tier"] == "S"
        # Every planted defect cites a file that exists in the emitted tree.
        corpus_root = output_root / language / "corpus"
        for defect in manifest["planted_defects"][:5]:
            assert (corpus_root / defect["file"]).is_file(), defect["file"]
