"""AC-2 (FR-3, NFR-3): byte-identical double-run determinism at tier S and L."""

import json
from pathlib import Path

from evaltools.corpus.generator import generate_corpus

PINNED_SEED = 194406
COMMITTED_CHECKSUM_MANIFEST_PATH = Path("evaltools/corpus/checksum-manifest.json")
DETERMINISM_RESULT_PATH = Path("results/determinism.json")
EXP1_RESULT_PATH = Path("results/exp1.json")


def _tree_sha256_from_manifest(manifest: dict) -> str:
    return manifest["tree_sha256"]


def test_committed_determinism_result_is_pass_and_tier_l() -> None:
    determinism = json.loads(DETERMINISM_RESULT_PATH.read_text(encoding="utf-8"))
    assert determinism["schema_version"] == "eval-schema 0.1.1"
    assert determinism["tier"] == "L"
    assert determinism["seed"] == PINNED_SEED
    assert determinism["byte_identical"] is True
    assert determinism["verdict"] == "PASS"
    assert determinism["run_a_tree_sha256"] == determinism["run_b_tree_sha256"], (
        "double-run tree hashes diverge"
    )

    committed_checksum = json.loads(
        COMMITTED_CHECKSUM_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    assert (
        _tree_sha256_from_manifest(committed_checksum)
        == determinism["run_a_tree_sha256"]
    ), (
        "committed checksum-manifest.json tree_sha256 does not match the "
        "determinism result's double-run hash"
    )

    exp1_result = json.loads(EXP1_RESULT_PATH.read_text(encoding="utf-8"))
    assert (
        exp1_result["checksum_manifest_tree_sha256"] == determinism["run_a_tree_sha256"]
    ), "results/exp1.json is not tied to the determinism-verified corpus bytes"


def _checksum_manifest_bytes(checksum_manifest_path: Path) -> bytes:
    return checksum_manifest_path.read_bytes()


def test_live_tier_s_double_run_is_byte_identical_both_languages(
    tmp_path: Path,
) -> None:
    """FR-3: regenerate tier S in tmp twice per language; manifests byte-identical."""
    output_root = tmp_path / "determinism-tier-s"
    for language in ("typescript_node", "python"):
        # generate_corpus writes <out>/<language>/, so pass the run root and
        # read the manifests under the per-language directory.
        run_a_root = output_root / "run_a"
        run_b_root = output_root / "run_b"
        generate_corpus(PINNED_SEED, "S", language, run_a_root)
        generate_corpus(PINNED_SEED, "S", language, run_b_root)
        run_a_dir = run_a_root / language
        run_b_dir = run_b_root / language
        manifest_a = _checksum_manifest_bytes(run_a_dir / "checksum-manifest.json")
        manifest_b = _checksum_manifest_bytes(run_b_dir / "checksum-manifest.json")
        assert manifest_a == manifest_b, (
            f"tier-S {language} checksum manifests diverge between run_a and run_b"
        )
        parsed_manifest = json.loads(manifest_a)
        assert len(parsed_manifest["files"]) > 0
        for file_entry in parsed_manifest["files"]:
            assert len(file_entry["sha256"]) == 64
            assert file_entry["size_bytes"] >= 0
