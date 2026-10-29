"""Block builders split out of evaltools/corpus/content_ts.py (style contract rule 8).

Pure functions over seed/stream arguments; no clock, randomness or I/O. The
assembler in the original module re-imports these names; behaviour is unchanged.
"""

from collections.abc import Callable


def _ts_cache_aside_block(entity: str, suffix: int) -> list[str]:
    """Correct cache-aside read: get, miss, database load, setex, return."""
    capitalized = entity.capitalize()
    return [
        (
            f"export async function load{capitalized}{suffix}(id: string):"
            f" Promise<{capitalized}Record> {{"
        ),
        f"  const cacheKey = `{entity}:${{id}}`;",
        "  const cached = await client.get(cacheKey);",
        "  if (cached !== null) {",
        f"    return JSON.parse(cached) as {capitalized}Record;",
        "  }",
        f"  const record = await database.load{capitalized}(id);",
        "  await client.setex(cacheKey, CACHE_TTL_SECONDS, JSON.stringify(record));",
        "  return record;",
        "}",
        "",
    ]


def _ts_pipeline_block(entity: str, suffix: int) -> list[str]:
    capitalized = entity.capitalize()
    return [
        (
            f"export async function warm{capitalized}{suffix}Cache(ids: string[]):"
            f" Promise<void> {{"
        ),
        "  const pipelineTxn = client.multi();",
        "  ids.forEach((id) => {",
        (
            f"    pipelineTxn.setex(`{entity}:${{id}}`, CACHE_TTL_SECONDS,"
            f" JSON.stringify({{ id }}));"
        ),
        "  });",
        "  await pipelineTxn.exec();",
        "}",
        "",
    ]


def _ts_lua_block(entity: str, suffix: int) -> list[str]:
    capitalized = entity.capitalize()
    return [
        f"const RATE_LIMIT_SCRIPT_{suffix} = `",
        "local current = redis.call('GET', KEYS[1])",
        "if not current then",
        "  redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])",
        "end",
        "return redis.call('GET', KEYS[1])",
        "`;",
        "",
        (
            f"export async function check{capitalized}{suffix}Rate(id: string, limit:"
            f" string, windowSeconds: string): Promise<string | null> {{"
        ),
        (
            f"  return client.eval(RATE_LIMIT_SCRIPT_{suffix}, 1,"
            f" `{entity}:${{id}}:limit`, limit, windowSeconds);"
        ),
        "}",
        "",
    ]


def _ts_pubsub_block(entity: str, suffix: int) -> list[str]:
    capitalized = entity.capitalize()
    return [
        (
            f"export async function broadcast{capitalized}{suffix}Event(id: string,"
            f" payload: string): Promise<void> {{"
        ),
        (
            f"  await client.publish(`events:{entity}`, JSON.stringify({{ id, payload"
            f" }}));"
        ),
        "}",
        "",
        (
            f"export async function watch{capitalized}{suffix}Events(onMessage:"
            f" (message: string) => void): Promise<void> {{"
        ),
        f"  await client.subscribe(`events:{entity}`);",
        (
            '  client.on("message", (channelName: string, message: string) =>'
            " onMessage(message));"
        ),
        "}",
        "",
    ]


def _ts_one_hop_block(entity: str, suffix: int) -> list[str]:
    capitalized = entity.capitalize()
    return [
        (
            f"export async function fetch{capitalized}{suffix}ThroughCache(id:"
            f" string): Promise<string | null> {{"
        ),
        f"  return client.get(`{entity}:${{id}}`);",
        "}",
        "",
    ]


def _ts_template_composition_block(entity: str, suffix: int) -> list[str]:
    capitalized = entity.capitalize()
    return [
        (
            f"export async function load{capitalized}{suffix}Shard(id: string, shard:"
            f" number): Promise<string | null> {{"
        ),
        f"  return client.get(`{entity}:${{id}}:shard:${{shard}}`);",
        "}",
        "",
    ]


_TS_PATTERN_BLOCK_BUILDERS: dict[str, Callable[[str, int], list[str]]] = {
    "pipeline": _ts_pipeline_block,
    "lua_script": _ts_lua_block,
    "pubsub": _ts_pubsub_block,
    "one_hop_wrapper": _ts_one_hop_block,
    "template_composition": _ts_template_composition_block,
}
