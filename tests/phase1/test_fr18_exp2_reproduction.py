"""AC-15 (FR-18): C-1/C-2 reproduce the recorded EXP-2 measurements exactly.

The tolerance string of ``results/exp2.json`` is: ``exact per-callsite match
on resolved_depth and tier; template_correct must match``. The reproduction
re-runs the EXP-2 harness (both measurement modes) into a pytest tmp path —
never into the committed result file — and compares every per-label row to
the committed artifact. Reading the pinned bullmq checkout is read-only.
"""

import json
from pathlib import Path

from conftest import checkout_root  # noqa: F401  (session fixture; skips without checkout)
from qa_support import LABELS_PATH, RESULTS_DIR

from evaltools.exp2.harness import RESULT_PATH, run_experiment

COMMITTED_EXP2 = RESULTS_DIR / "exp2.json"
COMMITTED_BYTES_BEFORE = COMMITTED_EXP2.read_bytes()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_reproduction_matches_the_recorded_exp2_artifact_per_callsite(
    checkout_root: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    committed = _load_json(COMMITTED_EXP2)
    run_experiment(
        labels_path=LABELS_PATH,
        result_path=tmp_path / "reproduced-exp2.json",
        mode="both",
    )
    reproduced = _load_json(tmp_path / "reproduced-exp2.json")
    for measurement_key in ("c1_only", "pipeline"):
        recorded_block = committed["measurements"][measurement_key]
        reproduced_block = reproduced["measurements"][measurement_key]
        recorded_rows = {row["callsite_id"]: row for row in recorded_block["per_label"]}
        reproduced_rows = {
            row["callsite_id"]: row for row in reproduced_block["per_label"]
        }
        assert set(recorded_rows) == set(reproduced_rows), (
            f"{measurement_key}: per-label ids diverge from the recorded artifact"
        )
        divergences: list[str] = []
        for callsite_id, recorded_row in recorded_rows.items():
            reproduced_row = reproduced_rows[callsite_id]
            for field in ("predicted", "predicted_method", "classification"):
                if recorded_row[field] != reproduced_row[field]:
                    divergences.append(
                        f"{measurement_key}/{callsite_id}.{field}: "
                        f"recorded {recorded_row[field]!r} vs reproduced "
                        f"{reproduced_row[field]!r}"
                    )
        assert not divergences, (
            "FR-18 tolerance violated (exact per-callsite match required): "
            f"{divergences}"
        )
        for count_field in (
            "true_positives",
            "false_positives",
            "false_negatives",
            "true_negatives",
        ):
            assert reproduced_block[count_field] == recorded_block[count_field]
        assert reproduced_block["verdict"] == recorded_block["verdict"]


def test_reproduction_leaves_the_committed_result_untouched(
    checkout_root: Path,  # noqa: F811
) -> None:
    """The committed results/exp2.json is frozen evidence; runs must not overwrite."""
    assert RESULT_PATH.name == "exp2.json"
    assert COMMITTED_EXP2.read_bytes() == COMMITTED_BYTES_BEFORE, (
        "the committed results/exp2.json changed during the reproduction run"
    )
