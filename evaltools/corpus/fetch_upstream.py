"""Fetch the pinned upstream bullmq checkout and write its corpus manifest.

Contract 2 §3.5 (corpus-and-experiments): EXP-2's labelled callsites come from
the upstream bullmq snapshot pinned at commit
``f42514c3d716dc81c2bbc65b883c9dc545fcb56d`` (upstream version 6.4.2, licence
MIT). This script fetches that exact commit
into a gitignored destination, verifies the resolved HEAD equals the pin
(fail fast on mismatch), and records the provenance evidence in
``results/corpus-manifest.json`` via the shared gate-evidence writer.

Behaviour:
- Stdlib only: ``git`` is invoked through ``subprocess``, nothing else leaves
  the process. No network access happens at import time.
- Idempotent: when the destination already resolves HEAD to the pin, the
  script reports "already at pin" and exits 0 without re-fetching.
- Fail fast: a destination that is not a git checkout, or that resolves to any
  other commit, is an error — the script never overwrites or "fixes" it.
- No vendoring: the destination lives under ``corpora/`` (gitignored per
  ADR-106); the manifest's ``vendored_tree_committed`` flag is computed from
  ``git ls-files`` and is never hand-asserted.
- Blocked runs still write the manifest with verdict
  ``blocked-pending-corpus``, naming the pinned SHA and the exact fetch
  command (Contract 2 §4), then exit non-zero.
"""

import argparse
import shutil
import subprocess  # noqa: S404  (git invocation for the pinned corpus fetch)
import sys
from datetime import UTC, datetime
from pathlib import Path

from evaltools.gate_evidence import SCHEMA_VERSION, write_result_json

PINNED_COMMIT_SHA = "f42514c3d716dc81c2bbc65b883c9dc545fcb56d"
UPSTREAM_URL = "https://github.com/taskforcesh/bullmq.git"
UPSTREAM_REPO_NAME = "bullmq"
UPSTREAM_VERSION_TAG = "v6.4.2"
UPSTREAM_VERSION = "6.4.2"
UPSTREAM_LICENCE = "MIT"
SOURCE_PATHS = ["src"]
DEFAULT_DESTINATION = "corpora/upstream/bullmq"
DEFAULT_MANIFEST_PATH = "results/corpus-manifest.json"
FETCH_COMMAND = (
    "uv run python -m evaltools.corpus.fetch_upstream --dest corpora/upstream/bullmq"
)

VERDICT_WHEN_PINNED = "pass"
VERDICT_WHEN_BLOCKED = "blocked-pending-corpus"


class UpstreamFetchError(RuntimeError):
    """Raised when the checkout cannot be proven to sit at the pinned commit."""


def _run_git(
    git_arguments: list[str], working_directory: Path, capture: bool = True
) -> str:
    """Run ``git`` in ``working_directory`` and return its stripped stdout.

    Fail fast: a non-zero exit or a missing git binary raises with the command
    and, when captured, the stderr text — never a silent empty result.
    """
    git_executable = shutil.which("git")
    if git_executable is None:
        raise UpstreamFetchError("git executable not found on PATH")
    completed = subprocess.run(
        [git_executable, *git_arguments],
        cwd=working_directory,
        capture_output=capture,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() if capture else ""
        raise UpstreamFetchError(
            f"git {' '.join(git_arguments)} failed with exit code "
            f"{completed.returncode}: {detail}"
        )
    return completed.stdout.strip() if capture else ""


def _read_resolved_head(checkout_path: Path) -> str:
    """Return the checkout's full 40-hex HEAD commit SHA."""
    return _run_git(["rev-parse", "HEAD"], checkout_path)


def _read_version_tag(checkout_path: Path) -> str:
    """Return the most recent tag reachable from HEAD (``git describe``).

    The upstream version is verified against the git tag, not
    ``package.json``: at the pinned commit the tag is ``v6.4.2`` while
    upstream's ``package.json`` still reads 6.4.1 (their release process
    lags the tag), so the tag is the authoritative version evidence.
    """
    return _run_git(["describe", "--tags", "--always"], checkout_path)


def _verify_checkout_matches_pin(checkout_path: Path) -> str:
    """Verify HEAD and the package version match the pin; return the HEAD SHA.

    Fail fast on any mismatch so a drifted or corrupted checkout can never be
    recorded as corpus provenance.
    """
    resolved_head = _read_resolved_head(checkout_path)
    if resolved_head != PINNED_COMMIT_SHA:
        raise UpstreamFetchError(
            f"checkout at {checkout_path} resolves HEAD {resolved_head}, "
            f"expected the pinned commit {PINNED_COMMIT_SHA}; delete "
            f"{checkout_path} and re-run: {FETCH_COMMAND}"
        )
    resolved_version_tag = _read_version_tag(checkout_path)
    if resolved_version_tag != UPSTREAM_VERSION_TAG:
        raise UpstreamFetchError(
            f"checkout at {checkout_path} describes HEAD as "
            f"{resolved_version_tag}, expected the tag {UPSTREAM_VERSION_TAG} "
            f"at the pinned commit {PINNED_COMMIT_SHA}"
        )
    return resolved_head


def _clone_and_checkout_pin(destination: Path) -> str:
    """Clone the upstream repository and detach onto the pinned commit."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"cloning {UPSTREAM_URL} into {destination} ...")
    subprocess.run(
        ["git", "clone", UPSTREAM_URL, str(destination)],
        check=False,
    )
    if not (destination / ".git").exists():
        raise UpstreamFetchError(
            f"clone did not produce a git checkout at {destination}"
        )
    _run_git(["checkout", "--detach", PINNED_COMMIT_SHA], destination)
    return _verify_checkout_matches_pin(destination)


def ensure_checkout_at_pin(destination: Path) -> str | None:
    """Make ``destination`` a git checkout at the pin and return its HEAD SHA.

    Returns ``None`` when the checkout could not be fetched; the caller turns
    that into the blocked-path manifest and a non-zero exit.
    """
    if destination.exists():
        if not (destination / ".git").exists():
            raise UpstreamFetchError(
                f"destination {destination} already exists and is not a git "
                f"checkout; remove it and re-run: {FETCH_COMMAND}"
            )
        resolved_head = _read_resolved_head(destination)
        if resolved_head != PINNED_COMMIT_SHA:
            raise UpstreamFetchError(
                f"checkout at {destination} resolves HEAD {resolved_head}, "
                f"expected the pinned commit {PINNED_COMMIT_SHA}; delete "
                f"{destination} and re-run: {FETCH_COMMAND}"
            )
        resolved_version_tag = _read_version_tag(destination)
        if resolved_version_tag != UPSTREAM_VERSION_TAG:
            raise UpstreamFetchError(
                f"checkout at {destination} describes HEAD as "
                f"{resolved_version_tag}, expected the tag "
                f"{UPSTREAM_VERSION_TAG} at the pinned commit {PINNED_COMMIT_SHA}"
            )
        print(
            f"already at pin: {destination} resolves HEAD {resolved_head} "
            f"(tag {resolved_version_tag}); nothing to fetch"
        )
        return resolved_head
    return _clone_and_checkout_pin(destination)


def _is_vendored_tree_committed() -> bool:
    """Return True when any ADR-106 corpus path is tracked by git.

    ADR-106 forbids committing ``corpora/`` or ``third_party/``; the check
    runs ``git ls-files`` from the current working directory (the repository
    root, per the documented fetch command) so the manifest flag is measured,
    never asserted.
    """
    tracked_files = _run_git(["ls-files", "--", "corpora", "third_party"], Path.cwd())
    return bool(tracked_files)


def build_manifest(resolved_head_sha: str | None) -> dict[str, object]:
    """Build the §3.5 manifest payload; the verdict is computed, not asserted."""
    checkout_resolves_to_pin = resolved_head_sha == PINNED_COMMIT_SHA
    verdict = VERDICT_WHEN_PINNED if checkout_resolves_to_pin else VERDICT_WHEN_BLOCKED
    fetch_date = datetime.now(UTC).date().isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": verdict,
        "vendored_tree_committed": _is_vendored_tree_committed(),
        "repos": [
            {
                "repo": UPSTREAM_REPO_NAME,
                "url": UPSTREAM_URL,
                "commit_sha": PINNED_COMMIT_SHA,
                "upstream_version": UPSTREAM_VERSION,
                "licence": UPSTREAM_LICENCE,
                "fetch_date": fetch_date,
                "source_paths": SOURCE_PATHS,
                "fetch_command": FETCH_COMMAND,
                "present": checkout_resolves_to_pin,
            }
        ],
    }


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch the pinned upstream bullmq checkout and write "
            "results/corpus-manifest.json (Contract 2 §3.5)."
        )
    )
    parser.add_argument(
        "--dest",
        default=DEFAULT_DESTINATION,
        help=f"destination checkout path (default: {DEFAULT_DESTINATION})",
    )
    parser.add_argument(
        "--manifest",
        default=DEFAULT_MANIFEST_PATH,
        help=f"manifest output path (default: {DEFAULT_MANIFEST_PATH})",
    )
    return parser.parse_args()


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_arguments()
    destination = Path(arguments.dest)
    try:
        resolved_head_sha = ensure_checkout_at_pin(destination)
    except UpstreamFetchError as fetch_error:
        print(f"error: {fetch_error}", file=sys.stderr)
        blocked_manifest = build_manifest(resolved_head_sha=None)
        write_result_json(arguments.manifest, blocked_manifest)
        print(
            f"wrote pending manifest {arguments.manifest} with verdict "
            f"{VERDICT_WHEN_BLOCKED} (pinned commit {PINNED_COMMIT_SHA}, "
            f"fetch command: {FETCH_COMMAND})",
            file=sys.stderr,
        )
        return 1
    manifest = build_manifest(resolved_head_sha)
    write_result_json(arguments.manifest, manifest)
    print(
        f"verified pin: HEAD {resolved_head_sha} at {destination}; "
        f"wrote manifest {arguments.manifest} with verdict {manifest['verdict']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
