"""CLI: ``python -m evaltools.corpus generate|determinism-check``.

``generate`` emits one corpus tree plus its three manifests per language.
``determinism-check`` runs the generator twice into separate directories,
compares the checksum manifests, computes the NFR-3/AC-2 verdict in code and
writes ``results/determinism.json`` atomically via ``write_result_json``.
"""

import argparse
import json
from pathlib import Path

from evaltools.corpus.generator import generate_corpus
from evaltools.corpus.model import LANGUAGES
from evaltools.gate_evidence import (
    SCHEMA_VERSION,
    load_result_json,
    require_known_enum,
    require_schema_version,
    write_result_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evaltools.corpus",
        description="Deterministic bilingual synthetic-corpus generator (FR-1..FR-5).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    generate_parser = commands.add_parser(
        "generate", help="Generate a corpus tree and manifests."
    )
    generate_parser.add_argument("--seed", type=int, required=True)
    generate_parser.add_argument("--tier", choices=["S", "M", "L"], required=True)
    generate_parser.add_argument(
        "--language",
        choices=[*LANGUAGES, "both"],
        required=True,
        help="Single language, or 'both' to emit the bilingual pair (FR-2).",
    )
    generate_parser.add_argument("--out", type=Path, required=True)

    determinism_parser = commands.add_parser(
        "determinism-check",
        help="Double-run one corpus and write results/determinism.json (AC-2, NFR-3).",
    )
    determinism_parser.add_argument("--seed", type=int, required=True)
    determinism_parser.add_argument("--tier", choices=["S", "L"], required=True)
    determinism_parser.add_argument("--language", choices=LANGUAGES, required=True)
    determinism_parser.add_argument("--out-root", type=Path, required=True)
    determinism_parser.add_argument("--result", type=Path, required=True)

    arguments = parser.parse_args(argv)
    if arguments.command == "generate":
        selected_languages = (
            LANGUAGES if arguments.language == "both" else (arguments.language,)
        )
        for language in selected_languages:
            statistics = generate_corpus(
                arguments.seed, arguments.tier, language, arguments.out
            )
            print(json.dumps(statistics, sort_keys=True))
        return 0
    return _run_determinism_check(arguments)


def _run_determinism_check(arguments: argparse.Namespace) -> int:
    for run_name in ("run_a", "run_b"):
        generate_corpus(
            arguments.seed,
            arguments.tier,
            arguments.language,
            Path(arguments.out_root) / run_name,
        )
    manifest_a = _load_checksum_manifest(
        Path(arguments.out_root)
        / "run_a"
        / arguments.language
        / "checksum-manifest.json"
    )
    manifest_b = _load_checksum_manifest(
        Path(arguments.out_root)
        / "run_b"
        / arguments.language
        / "checksum-manifest.json"
    )
    files_identical = manifest_a["files"] == manifest_b["files"]
    byte_identical = bool(
        files_identical and manifest_a["tree_sha256"] == manifest_b["tree_sha256"]
    )
    verdict = "PASS" if byte_identical else "FAIL"
    require_known_enum(verdict, ("PASS", "FAIL"), "results/determinism.json", "verdict")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "seed": arguments.seed,
        "tier": arguments.tier,
        "language": arguments.language,
        "run_a_tree_sha256": str(manifest_a["tree_sha256"]),
        "run_b_tree_sha256": str(manifest_b["tree_sha256"]),
        "byte_identical": byte_identical,
        "verdict": verdict,
    }
    write_result_json(arguments.result, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def _load_checksum_manifest(manifest_path: Path) -> dict[str, object]:
    payload = load_result_json(manifest_path)
    require_schema_version(payload, SCHEMA_VERSION)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
