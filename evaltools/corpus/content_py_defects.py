"""Block builders split out of evaltools/corpus/content_py.py (style contract rule 8).

Pure functions over seed/stream arguments; no clock, randomness or I/O. The
assembler in the original module re-imports these names; behaviour is unchanged.
"""


from evaltools.corpus.content import (
    DefectSpec,
    locate_span,
)
from evaltools.corpus.prng import derive_int


def _py_missing_ttl_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[DefectSpec]]:
    """Cache write without a TTL: `set` where `setex` is required (TTL-001)."""
    suffix = derive_int(seed, f"{stream}:defect", 0, 1000)
    defect_statement = "client.set(cache_key, json.dumps(record))"
    block = [
        f"def cache_{entity}_{suffix}(record_id: str, record: dict) -> None:",
        f"    cache_key = f'{entity}:{{record_id}}'",
        f"    {defect_statement}",
        "",
        "",
    ]
    specs = [
        DefectSpec(rule_id="TTL-001", span=locate_span(block, 2, defect_statement))
    ]
    return block, specs


def _py_missing_invalidation_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[DefectSpec]]:
    """Mutation refreshes the primary key but never invalidates the derived
    ``:profile`` key cached in the same scope (INV-002)."""
    suffix = derive_int(seed, f"{stream}:defect", 0, 1000)
    mutation_statement = f"database.save_{entity}(record_id, record)"
    block = [
        f"def load_{entity}_{suffix}_profile(record_id: str):",
        f"    profile_key = f'{entity}:{{record_id}}:profile'",
        "    cached = client.get(profile_key)",
        "    if cached is not None:",
        "        return json.loads(cached)",
        f"    record = database.load_{entity}(record_id)",
        "    client.setex(profile_key, CACHE_TTL_SECONDS, json.dumps(record))",
        "    return record",
        "",
        "",
        f"def update_{entity}_{suffix}(record_id: str, record: dict) -> None:",
        f"    {mutation_statement}",
        f"    cache_key = f'{entity}:{{record_id}}'",
        "    client.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(record))",
        "",
        "",
    ]
    specs = [
        DefectSpec(rule_id="INV-002", span=locate_span(block, 11, mutation_statement))
    ]
    return block, specs


def _py_namespace_mismatch_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[DefectSpec]]:
    """Same logical entity cached under the plural ``users:`` namespace (NS-003)."""
    suffix = derive_int(seed, f"{stream}:defect", 0, 1000)
    mismatched_template = "f'users:{record_id}'"
    block = [
        f"def load_{entity}_{suffix}_legacy(record_id: str):",
        f"    legacy_key = {mismatched_template}",
        "    return client.get(legacy_key)",
        "",
        "",
    ]
    specs = [
        DefectSpec(rule_id="NS-003", span=locate_span(block, 1, mismatched_template))
    ]
    return block, specs


def _py_read_modify_write_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[DefectSpec]]:
    """Non-atomic read-modify-write on a counter (RACE-004)."""
    suffix = derive_int(seed, f"{stream}:defect", 0, 1000)
    read_statement = "current = client.get(counter_key)"
    write_statement = "client.set(counter_key, str(next_value))"
    block = [
        f"def bump_{entity}_{suffix}_counter(record_id: str) -> int:",
        f"    counter_key = f'counter:{entity}:{{record_id}}'",
        f"    {read_statement}",
        "    next_value = int(current or 0) + 1",
        f"    {write_statement}",
        "    return next_value",
        "",
        "",
    ]
    specs = [
        DefectSpec(
            rule_id="RACE-004",
            span=locate_span(block, 2, read_statement, 4, write_statement),
        )
    ]
    return block, specs
