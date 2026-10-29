"""AC-5 (FR-6, NFR-1): the committed EXP-1 result records the required evidence."""

import json
from pathlib import Path

EXP1_RESULT_PATH = Path("results/exp1.json")
CHECKSUM_MANIFEST_PATH = Path("evaltools/corpus/checksum-manifest.json")
DETERMINISM_RESULT_PATH = Path("results/determinism.json")
EXPECTED_PATTERN_COUNT = 100
ADVISORY_VERDICTS = ("advisory-pass", "advisory-fail")
REFERENCE_VERDICTS = ("PASS", "FAIL")


def test_exp1_result_records_p95_environment_and_verdict() -> None:
    result = json.loads(EXP1_RESULT_PATH.read_text(encoding="utf-8"))
    assert result["schema_version"] == "eval-schema 0.1.1"
    assert result["pattern_count"] == EXPECTED_PATTERN_COUNT
    assert (
        isinstance(result["p95_wall_ms"], (int, float)) and result["p95_wall_ms"] >= 0
    )
    assert isinstance(result["edge_count"], int) and result["edge_count"] >= 0
    # per_pattern_ms is either one value per pattern or a percentile summary
    # block — the harness's fixed choice (Contract 2 §3.6).
    per_pattern = result["per_pattern_ms"]
    assert isinstance(per_pattern, (list, dict))
    if isinstance(per_pattern, list):
        assert len(per_pattern) == EXPECTED_PATTERN_COUNT

    environment = result["measurement_environment"]
    assert environment["label"] in ("reference", "advisory")
    assert isinstance(environment["is_reference_profile"], bool)
    assert environment["ram_gb"] == 8
    # FR-11 honesty: an 8 GB machine never certifies the reference profile.
    assert environment["label"] == "advisory"
    assert environment["is_reference_profile"] is False
    # The label and the verdict must agree (Contract 2 §3.6 verdict rules).
    if environment["label"] == "advisory":
        assert result["verdict"] in ADVISORY_VERDICTS
    else:
        assert result["verdict"] in REFERENCE_VERDICTS


def test_exp1_result_is_tied_to_the_determinism_verified_corpus() -> None:
    result = json.loads(EXP1_RESULT_PATH.read_text(encoding="utf-8"))
    checksum_manifest = json.loads(CHECKSUM_MANIFEST_PATH.read_text(encoding="utf-8"))
    determinism = json.loads(DETERMINISM_RESULT_PATH.read_text(encoding="utf-8"))
    assert result["checksum_manifest_tree_sha256"] == checksum_manifest["tree_sha256"]
    assert determinism["run_a_tree_sha256"] == checksum_manifest["tree_sha256"]
