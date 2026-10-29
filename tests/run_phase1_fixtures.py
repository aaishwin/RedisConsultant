"""qa fixture runner: computes results/phase1-fixtures.json from real executions.

Contract 2 §3.10: every verdict field is computed by this runner from the
pytest group outcomes and the live invariant checks below — never hand-asserted.
Run with: ``uv run python tests/run_phase1_fixtures.py``
"""

import hashlib
import importlib.util
import subprocess  # noqa: S404  (invokes the fixture-generation subprocess)
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # repo root: redis_intel / evaltools packages
sys.path.insert(1, str(HERE))  # tests dir: conftest + qa_support
sys.path.insert(
    2, str(HERE / "phase1")
)  # phase1 test modules for the round-trip builder

# sys.path bootstrap must precede these imports: redis_intel / evaltools are
# repo packages (not installed in the venv), conftest / qa_support live in
# tests/, and the phase1 test modules in tests/phase1/. E402 deviations are
# deliberate and documented inline.
import qa_support  # noqa: E402  (needs the sys.path bootstrap above)
from conftest import count_silent_drops, ingest_sources  # noqa: E402  (needs sys.path bootstrap)

from redis_intel.frontend import LanguageFrontend  # noqa: E402  (needs sys.path bootstrap)
from redis_intel.ir import serialize  # noqa: E402  (needs sys.path bootstrap)
from redis_intel.ir.models import IR_SCHEMA_VERSION  # noqa: E402  (needs sys.path bootstrap)

REPO_ROOT = qa_support.REPO_ROOT
RESULT_PATH = REPO_ROOT / "results" / "phase1-fixtures.json"

# AC group → test files whose exit code decides the per_ac status.
AC_GROUPS: dict[str, list[str]] = {
    "AC-11": ["tests/phase1/test_grammar_matrix.py"],
    "AC-12": ["tests/phase1/test_unknown_drops.py"],
    "AC-13": ["tests/phase1/test_serialization_roundtrip.py"],
    "AC-14": ["tests/phase1/test_wrapper_depth.py"],
    "AC-15": ["tests/phase1/test_fr18_exp2_reproduction.py"],
    "AC-16": ["tests/phase1/test_conn_config_redaction.py"],
    "AC-17": ["tests/phase1/test_epistemic_tiers.py"],
    "AC-18": ["tests/phase1/test_parser_pins.py"],
    "AC-19": ["tests/phase1/test_resolution_rules.py"],
    "AC-20": ["tests/phase1/test_exp2_negatives.py"],
}

PER_AC_EVIDENCE = {
    "AC-11": (
        "grammar registry matrix + per-extension ParseResult"
        " grammar_id/grammar_version (tests/phase1/test_grammar_matrix.py);"
        " .tsx ⇒ tsx, never typescript (structural ERROR divergence proven)"
    ),
    "AC-12": (
        "drop counter == 0 over the ingestable Phase-1 fixture corpus; escalation"
        " fixtures produce explicit unknowns entries"
        " (tests/phase1/test_unknown_drops.py); unsupported-syntax construct"
        " accounted at C-1 level and at C-2 as a recorded unknowns entry"
        " (subject_kind=file, reason=unsupported_syntax) with no files row"
        " (FileRow.grammar_id has no 'unsupported' member) — fixed in debug"
        " attempt 1"
    ),
    "AC-13": (
        "all 14 entity kinds present; serialize(deserialize(serialize(d)))"
        " byte-equal + structural equality"
        " (tests/phase1/test_serialization_roundtrip.py); INVALIDATES/test-ref kinds"
        " exercised at the serialization layer (builder does not emit them in Phase"
        " 1)"
    ),
    "AC-14": (
        "depth 0/1/2 concrete via the public pipeline with DEPTH recorded on client"
        " rows and edges; depth-3 escalation (UNKNOWN + wrapper_depth_exceeded +"
        " model_hypothesis_candidate + DEPTH 3) verified at the ClientChainResolver"
        " level because the C-1 receiver gate (contract-conformant R5) never emits"
        " >1-hop receivers (tests/phase1/test_wrapper_depth.py)"
    ),
    "AC-15": (
        "FR-18 reproduction re-runs the EXP-2 harness into tmp and matches the"
        " committed results/exp2.json per-callsite exactly (both measurement blocks)"
        " (tests/phase1/test_fr18_exp2_reproduction.py)"
    ),
    "AC-16": (
        "sentinel secrets appear unredacted nowhere in the serialized IR: the"
        " construction call's config argument no longer becomes a key expression"
        " (debug attempt 1); every clients.conn_config row is redacted via the"
        " governance seam, redact(redact(x)) == redact(x), non-mapping input raises"
        " TypeError"
        " (tests/phase1/test_conn_config_redaction.py::"
        "test_sentinel_never_appears_in_any_ir_row_or_artifact)"
    ),
    "AC-17": (
        "epistemic present and six-tier on every claim-bearing row of the fixture"
        " IrDelta, before and after the round trip"
        " (tests/phase1/test_epistemic_tiers.py)"
    ),
    "AC-18": (
        "pyproject.toml pins tree-sitter==0.23.2 / tree-sitter-typescript==0.23.2 /"
        " tree-sitter-javascript==0.23.1; no tree-sitter-language-pack in pyproject"
        " or uv.lock; socket-guarded parse per grammar succeeds"
        " (tests/phase1/test_parser_pins.py)"
    ),
    "AC-19": (
        "one fixture per §3.4 rev-3 rule: R1 class_field_initializer (DEPTH 0),"
        " R2 constructor_injection (DEPTH 1, STATIC_INFERENCE, annotation"
        " construction), R3 factory_return (DEPTH 1; factory over R2 injection"
        " reaches DEPTH 2 concrete), R4 dynamic_require both forms (DEPTH 0),"
        " R5 negative never a callsite with one recorded unresolvable_expression"
        " entry; drop count 0 across the set"
        " (tests/phase1/test_resolution_rules.py)"
    ),
    "AC-20": (
        "all 14 negative EXP-2 labels stay true negatives: zero false positives in"
        " the harness-shaped re-run and zero same-method callsites on every negative"
        " span (tests/phase1/test_exp2_negatives.py)"
    ),
}


def run_pytest_group(test_files: list[str]) -> int:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *test_files],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=600,
    )
    return completed.returncode


def compute_grammar_id_matrix() -> dict[str, str]:
    frontend = LanguageFrontend()
    matrix: dict[str, str] = {}
    for path, source in qa_support.GRAMMAR_MATRIX_SOURCES.items():
        parse_result = frontend.parse(path, source.encode())
        matrix[path] = parse_result.grammar_id
    matrix["unsupported .py"] = frontend.parse("plain.py", b"x = 1\n").grammar_id
    return matrix


def compute_unknown_drop_count() -> int:
    frontend = LanguageFrontend()
    ingestable_sources = {
        path: source
        for path, source in qa_support.PHASE1_FIXTURE_SOURCES.items()
        if path != "unsupported_syntax.py"
    }
    parse_results, delta = ingest_sources(frontend, ingestable_sources)
    drops = count_silent_drops(parse_results, delta)
    return len(drops)


def compute_sentinel_scan() -> dict[str, object]:
    frontend = LanguageFrontend()
    parse_results, delta = ingest_sources(
        frontend,
        {
            "sentinel_secrets.ts": qa_support.PHASE1_FIXTURE_SOURCES[
                "sentinel_secrets.ts"
            ]
        },
    )
    assert parse_results, "sentinel fixture must parse"
    serialized = serialize(delta).decode("utf-8")
    matches = sum(1 for sentinel in qa_support.SENTINELS if sentinel in serialized)
    # Idempotence of the governance seam itself (redact(redact(x)) == redact(x)).
    from redis_intel.governance.conn_config_redaction import redact_conn_config

    probe_config = {
        "host": "h",
        "password": qa_support.SENTINEL_CONFIG_PASSWORD,
        "url": f"redis://admin:{qa_support.SENTINEL_URI_PASSWORD}@h:6379",
    }
    first_pass = redact_conn_config(probe_config)
    second_pass = redact_conn_config(first_pass)
    idempotence = "pass" if first_pass == second_pass else "fail"
    return {
        "files_scanned": 1,
        "matches": matches,
        "idempotence_check": idempotence,
        "note": (
            "matches must stay 0: any match would be the AC-16 leak returning "
            "(a construction call's config argument reaching the serialized IR "
            "unredacted). Fixed in debug attempt 1; every clients.conn_config "
            "row is redacted via the governance seam"
        ),
    }


def compute_round_trip_checksum() -> dict[str, object]:
    # test_serialization_roundtrip lives in tests/phase1/ and is only importable
    # via the sys.path bootstrap above, so load it by explicit file location.
    roundtrip_module_path = HERE / "phase1" / "test_serialization_roundtrip.py"
    roundtrip_spec = importlib.util.spec_from_file_location(
        "test_serialization_roundtrip", roundtrip_module_path
    )
    assert roundtrip_spec and roundtrip_spec.loader, (
        f"cannot load {roundtrip_module_path}"
    )
    roundtrip_module = importlib.util.module_from_spec(roundtrip_spec)
    roundtrip_spec.loader.exec_module(roundtrip_module)
    build_all_fourteen_kinds_delta = roundtrip_module.build_all_fourteen_kinds_delta

    frontend = LanguageFrontend()
    delta = build_all_fourteen_kinds_delta(frontend)
    first_serialization = serialize(delta)
    from redis_intel.ir import deserialize

    deserialized = deserialize(first_serialization)
    second_serialization = serialize(deserialized)
    equal = second_serialization == first_serialization
    return {
        "fixture": (
            "all_fourteen_kinds (+ INVALIDATES/test-ref rows at the serialization"
            " layer)"
        ),
        "serialized_sha256": hashlib.sha256(first_serialization).hexdigest(),
        "deserialized_resha256": hashlib.sha256(second_serialization).hexdigest(),
        "equal": equal,
        "ir_schema_version": IR_SCHEMA_VERSION,
    }


def collect_fixture_names() -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/phase1"],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )
    names = [
        line.strip()
        for line in completed.stdout.splitlines()
        if "::" in line and line.strip().startswith("tests/")
    ]
    return names


def main() -> int:
    per_ac: dict[str, dict[str, str]] = {}
    for ac_id, test_files in AC_GROUPS.items():
        exit_code = run_pytest_group(test_files)
        status = "pass" if exit_code == 0 else "fail"
        per_ac[ac_id] = {"status": status, "evidence": PER_AC_EVIDENCE[ac_id]}

    sentinel_scan = compute_sentinel_scan()
    round_trip = compute_round_trip_checksum()
    label_audit = qa_support.audit_labels()
    required_invariants_hold = (
        sentinel_scan["matches"] == 0
        and sentinel_scan["idempotence_check"] == "pass"
        and round_trip["equal"] is True
        and label_audit["result"] == "pass"
    )
    all_per_ac_pass = all(entry["status"] == "pass" for entry in per_ac.values())
    verdict = "pass" if all_per_ac_pass and required_invariants_hold else "fail"

    payload = {
        "schema_version": "eval-schema 0.1.1",
        "artifact": "results/phase1-fixtures.json",
        "verdict": verdict,
        "fixture_names": collect_fixture_names(),
        "per_ac": per_ac,
        "unknown_drop_count": compute_unknown_drop_count(),
        "sentinel_secret_scan": sentinel_scan,
        "round_trip_checksum": round_trip,
        "grammar_id_matrix": compute_grammar_id_matrix(),
        "label_audit": label_audit,
    }
    from evaltools.gate_evidence import write_result_json

    write_result_json(RESULT_PATH, payload)
    print(f"wrote {RESULT_PATH} verdict={verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
