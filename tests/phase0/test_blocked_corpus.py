"""AC-8 (FR-9): the offline blocked-corpus path writes a pending manifest."""

import json
import subprocess  # noqa: S404  (invokes the offline corpus writer subprocess)
import sys
from pathlib import Path

from evaltools.corpus.fetch_upstream import (
    FETCH_COMMAND,
    PINNED_COMMIT_SHA,
    UpstreamFetchError,
    build_manifest,
)


def test_blocked_manifest_names_the_pin_and_fetch_command(tmp_path: Path) -> None:
    """build_manifest(None) is exactly the FR-9 blocked outcome, written to disk."""
    from evaltools.gate_evidence import write_result_json

    blocked_manifest = build_manifest(resolved_head_sha=None)
    assert blocked_manifest["verdict"] == "blocked-pending-corpus"
    manifest_path = tmp_path / "blocked-manifest.json"
    write_result_json(manifest_path, blocked_manifest)
    # Adjudicate the written bytes (the artifact the gate would consume).
    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written["verdict"] == "blocked-pending-corpus"
    repo_entry = written["repos"][0]
    assert repo_entry["commit_sha"] == PINNED_COMMIT_SHA
    assert repo_entry["fetch_command"] == FETCH_COMMAND
    assert repo_entry["present"] is False


def test_offline_invocation_exits_nonzero_and_writes_pending_manifest(
    tmp_path: Path,
) -> None:
    """A destination that exists but is not a git checkout fails fast offline.

    The failure occurs before any clone attempt, so this exercises the blocked
    path with zero network access; the pending manifest is still written (a
    missing result file is never a valid outcome, Contract 2 §4).
    """
    fake_destination = tmp_path / "not-a-checkout"
    fake_destination.mkdir()
    manifest_path = tmp_path / "manifest.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "evaltools.corpus.fetch_upstream",
            "--dest",
            str(fake_destination),
            "--manifest",
            str(manifest_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
        timeout=60,
    )
    assert completed.returncode == 1, completed.stderr
    assert "blocked-pending-corpus" in completed.stderr
    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written["verdict"] == "blocked-pending-corpus"
    assert written["repos"][0]["commit_sha"] == PINNED_COMMIT_SHA
    assert written["repos"][0]["fetch_command"]


def test_a_misresolved_checkout_raises_instead_of_silent_overwrite(
    tmp_path: Path,
) -> None:
    """Fail-fast posture: a checkout at the wrong commit is an error, never fixed."""
    fake_checkout = tmp_path / "wrong-pin"
    (fake_checkout / ".git").mkdir(parents=True)
    # _read_resolved_head runs `git rev-parse HEAD` in the destination; an empty
    # non-repo directory makes git fail, surfacing UpstreamFetchError.
    try:
        from evaltools.corpus.fetch_upstream import ensure_checkout_at_pin

        ensure_checkout_at_pin(fake_checkout)
    except UpstreamFetchError as fetch_error:
        assert "resolve" in str(fetch_error) or "failed" in str(fetch_error)
    else:
        raise AssertionError("a non-git destination must raise UpstreamFetchError")
