"""CLI: ``uv run python -m evaltools.exp1 --seed 194406 --tier S
--language typescript_node``.

Runs the EXP-1 matching-cost experiment and atomically writes the result
artifact (default ``results/exp1.json``). Fail fast on any bad argument;
prints the per-rung p50/p95/max and the code-computed verdict.
"""

import argparse
import tempfile
from pathlib import Path

from evaltools.corpus.model import LANGUAGES
from evaltools.exp1.harness import ExperimentSummary, run_experiment

DEFAULT_RESULT_PATH = Path("results/exp1.json")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evaltools.exp1",
        description="EXP-1: the 100-pattern matching-cost harness (FR-6, FR-7, NFR-1).",
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--tier", choices=["S", "M", "L"], required=True)
    parser.add_argument("--language", choices=LANGUAGES, required=True)
    parser.add_argument("--result", type=Path, default=DEFAULT_RESULT_PATH)
    # Throwaway measurement corpus; the platform temp directory (typically
    # /tmp) is resolved at runtime, never hardcoded into the artifact.
    parser.add_argument("--corpus-root", type=Path, default=None)
    return parser


def print_experiment_summary(summary: ExperimentSummary) -> None:
    print(f"pattern_count: {summary.pattern_count}")
    print(f"edge_count: {summary.edge_count}")
    print(
        f"baseline p50/p95/max ms: "
        f"{summary.baseline_p50_ms:.3f}/{summary.baseline_p95_ms:.3f}/"
        f"{summary.baseline_max_ms:.3f}"
    )
    for rung_evidence in summary.escalation_rungs:
        print(
            f"rung {rung_evidence.rung}: p95 {rung_evidence.measured_p95_ms:.3f} ms "
            f"-> {rung_evidence.outcome}"
        )
    print(f"measurement label: {summary.measurement_label}")
    print(f"verdict: {summary.verdict}")
    print(f"result written: {summary.result_path}")


def main() -> None:
    """Parse the CLI arguments, run the experiment, print the typed summary."""
    arguments = build_argument_parser().parse_args()
    corpus_root = arguments.corpus_root or Path(tempfile.gettempdir()) / "exp1-corpus"
    summary = run_experiment(
        seed=arguments.seed,
        tier=arguments.tier,
        language=arguments.language,
        result_path=arguments.result,
        corpus_root=corpus_root,
    )
    print_experiment_summary(summary)


if __name__ == "__main__":
    main()
