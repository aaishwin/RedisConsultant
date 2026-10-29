"""Block builders split out of evaltools/corpus/content_ts.py (style contract rule 8).

Pure functions over seed/stream arguments; no clock, randomness or I/O. The
assembler in the original module re-imports these names; behaviour is unchanged.
"""


from evaltools.corpus.content import (
    DefectSpec,
    locate_span,
)
from evaltools.corpus.prng import derive_int


def _ts_missing_ttl_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[DefectSpec]]:
    """Cache write without a TTL: `set` where `setex` is required (TTL-001)."""
    capitalized = entity.capitalize()
    suffix = derive_int(seed, f"{stream}:defect", 0, 1000)
    defect_statement = "await client.set(cacheKey, JSON.stringify(record));"
    block = [
        (
            f"export async function cache{capitalized}{suffix}Record(id: string,"
            f" record: {capitalized}Record): Promise<void> {{"
        ),
        f"  const cacheKey = `{entity}:${{id}}`;",
        f"  {defect_statement}",
        "}",
        "",
    ]
    specs = [
        DefectSpec(rule_id="TTL-001", span=locate_span(block, 2, defect_statement))
    ]
    return block, specs


def _ts_missing_invalidation_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[DefectSpec]]:
    """Mutation refreshes the primary key but never invalidates the derived
    ``:profile`` key cached in the same scope (INV-002)."""
    capitalized = entity.capitalize()
    suffix = derive_int(seed, f"{stream}:defect", 0, 1000)
    mutation_statement = f"await database.save{capitalized}(id, record);"
    block = [
        (
            f"export async function load{capitalized}{suffix}Profile(id: string):"
            f" Promise<{capitalized}Record> {{"
        ),
        f"  const profileKey = `{entity}:${{id}}:profile`;",
        "  const cached = await client.get(profileKey);",
        "  if (cached !== null) {",
        f"    return JSON.parse(cached) as {capitalized}Record;",
        "  }",
        f"  const record = await database.load{capitalized}(id);",
        "  await client.setex(profileKey, CACHE_TTL_SECONDS, JSON.stringify(record));",
        "  return record;",
        "}",
        "",
        (
            f"export async function update{capitalized}{suffix}(id: string, record:"
            f" {capitalized}Record): Promise<void> {{"
        ),
        f"  {mutation_statement}",
        f"  const cacheKey = `{entity}:${{id}}`;",
        "  await client.setex(cacheKey, CACHE_TTL_SECONDS, JSON.stringify(record));",
        "}",
        "",
    ]
    specs = [
        DefectSpec(rule_id="INV-002", span=locate_span(block, 12, mutation_statement))
    ]
    return block, specs


def _ts_namespace_mismatch_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[DefectSpec]]:
    """Same logical entity cached under the plural ``users:`` namespace (NS-003)."""
    suffix = derive_int(seed, f"{stream}:defect", 0, 1000)
    mismatched_template = "`users:${id}`"
    block = [
        (
            f"export async function load{entity.capitalize()}{suffix}Legacy(id:"
            f" string): Promise<string | null> {{"
        ),
        f"  const legacyKey = {mismatched_template};",
        "  return client.get(legacyKey);",
        "}",
        "",
    ]
    specs = [
        DefectSpec(rule_id="NS-003", span=locate_span(block, 1, mismatched_template))
    ]
    return block, specs


def _ts_read_modify_write_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[DefectSpec]]:
    """Non-atomic read-modify-write on a counter (RACE-004)."""
    capitalized = entity.capitalize()
    suffix = derive_int(seed, f"{stream}:defect", 0, 1000)
    read_statement = "const current = await client.get(counterKey);"
    write_statement = "await client.set(counterKey, String(next));"
    block = [
        (
            f"export async function bump{capitalized}{suffix}Counter(id: string):"
            f" Promise<number> {{"
        ),
        f"  const counterKey = `counter:{entity}:${{id}}`;",
        f"  {read_statement}",
        '  const next = Number(current ?? "0") + 1;',
        f"  {write_statement}",
        "  return next;",
        "}",
        "",
    ]
    specs = [
        DefectSpec(
            rule_id="RACE-004",
            span=locate_span(block, 2, read_statement, 4, write_statement),
        )
    ]
    return block, specs
