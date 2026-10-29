"""AC-16 (FR-20, NFR-4): sentinel secrets never leak; redaction is idempotent."""

from typing import Any

import pytest
from conftest import ingest_sources
from qa_support import (
    PHASE1_FIXTURE_SOURCES,
    SENTINEL_CONFIG_PASSWORD,
    SENTINEL_URI_PASSWORD,
    SENTINELS,
)

from redis_intel.frontend import LanguageFrontend
from redis_intel.governance.conn_config_redaction import (
    REDACTION_PLACEHOLDER,
    redact_conn_config,
)
from redis_intel.ir import IrBuilder, serialize


@pytest.fixture(scope="module")
def frontend() -> LanguageFrontend:
    return LanguageFrontend()


def test_redaction_is_idempotent_and_pure() -> None:
    config: dict[str, Any] = {
        "host": "h",
        "password": SENTINEL_CONFIG_PASSWORD,
        "url": f"redis://admin:{SENTINEL_URI_PASSWORD}@h:6379?password={SENTINEL_URI_PASSWORD}",
        "nested": {"token": "t", "keep": 1},
        "list_of_uris": [f"rediss://user:{SENTINEL_URI_PASSWORD}@h:6380"],
    }
    snapshot = repr(config)
    first_pass = redact_conn_config(config)
    second_pass = redact_conn_config(first_pass)
    assert first_pass == second_pass, "redact(redact(x)) != redact(x)"
    assert repr(config) == snapshot, "redaction mutated its input"
    assert first_pass["password"] == REDACTION_PLACEHOLDER


def test_redaction_raises_typeerror_on_non_mapping() -> None:
    with pytest.raises(TypeError):
        redact_conn_config(["not", "a", "mapping"])  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        redact_conn_config("redis://x")  # type: ignore[arg-type]


def test_conn_config_rows_contain_no_sentinel(frontend: LanguageFrontend) -> None:
    """The clients rows themselves are redacted at the sanctioned seam."""
    parse_results, delta = ingest_sources(
        frontend, {"sentinel_secrets.ts": PHASE1_FIXTURE_SOURCES["sentinel_secrets.ts"]}
    )
    assert parse_results, "fixture corpus must parse before the scan"
    for sentinel in SENTINELS:
        for client in delta.clients:
            assert sentinel not in str(dict(client.conn_config)), (
                f"sentinel leaked into a clients.conn_config row: {client.construction}"
            )


def test_sentinel_never_appears_in_any_ir_row_or_artifact(
    frontend: LanguageFrontend,
) -> None:
    """NFR-4/AC-16: zero sentinel occurrences in the whole serialized IrDelta.

    KNOWN DEFECT REPRODUCTION (recorded 2026-10-28, qa run-1): the IrBuilder
    treats the construction call's first argument as a key expression, so the
    raw connection-config object literal (and a raw credential URI) are stored
    unredacted in ``key_exprs`` rows. This test is the regression coverage: it
    fails while the defect exists and must pass once the leak is fixed.
    """
    _parse_results, delta = ingest_sources(
        frontend, {"sentinel_secrets.ts": PHASE1_FIXTURE_SOURCES["sentinel_secrets.ts"]}
    )
    serialized = serialize(delta).decode("utf-8")
    leaked_in: list[str] = []
    for sentinel in SENTINELS:
        if sentinel in serialized:
            leaked_in.append(sentinel)
    assert not leaked_in, (
        f"sentinel secrets {leaked_in} appear unredacted in the serialized IR; "
        "the construction call's config argument is mirrored into key_exprs "
        "rows without passing the governance redaction seam (NFR-4 violation)"
    )
    # The seam itself must still have been applied to every conn_config.
    redacted_configs = [
        client.conn_config
        for client in delta.clients
        if REDACTION_PLACEHOLDER in str(dict(client.conn_config))
    ]
    assert redacted_configs, "no clients row shows the redaction placeholder"


def test_builder_invokes_the_governance_seam_per_clients_row(
    frontend: LanguageFrontend,
) -> None:
    """The redactor seam is invoked for every clients row construction."""
    calls: list[int] = []

    def counting_redactor(config: Any) -> Any:
        calls.append(1)
        return redact_conn_config(config)

    parse_result = frontend.parse(
        "direct_construction.ts",
        PHASE1_FIXTURE_SOURCES["direct_construction.ts"].encode("utf-8"),
    )
    IrBuilder.ingest([parse_result], redactor=counting_redactor)
    parse_result_clients = (
        2  # one 'new' construction callsite + one resolved receiver row
    )
    assert len(calls) == parse_result_clients
