"""Block builders split out of evaltools/corpus/content_py.py (style contract rule 8).

Pure functions over seed/stream arguments; no clock, randomness or I/O. The
assembler in the original module re-imports these names; behaviour is unchanged.
"""

from collections.abc import Callable


def _py_cache_aside_block(entity: str, suffix: int) -> list[str]:
    """Correct cache-aside read: get, miss, database load, setex, return."""
    return [
        "",
        f"def load_{entity}_{suffix}(record_id: str):",
        f"    cache_key = f'{entity}:{{record_id}}'",
        "    cached = client.get(cache_key)",
        "    if cached is not None:",
        "        return json.loads(cached)",
        f"    record = database.load_{entity}(record_id)",
        "    client.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(record))",
        "    return record",
        "",
        "",
    ]


def _py_pipeline_block(entity: str, suffix: int) -> list[str]:
    return [
        "",
        f"def warm_{entity}_{suffix}_cache(record_ids: list[str]) -> None:",
        "    with client.pipeline() as pipe:",
        "        for record_id in record_ids:",
        (
            f"            pipe.setex(f'{entity}:{{record_id}}', CACHE_TTL_SECONDS,"
            f" json.dumps({{'id': record_id}}))"
        ),
        "        pipe.execute()",
        "",
        "",
    ]


def _py_lua_block(entity: str, suffix: int) -> list[str]:
    return [
        "",
        f'RATE_LIMIT_SCRIPT_{suffix} = """',
        "local current = redis.call('GET', KEYS[1])",
        "if not current then",
        "  redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])",
        "end",
        "return redis.call('GET', KEYS[1])",
        '"""',
        "",
        "",
        (
            f"def check_{entity}_{suffix}_rate(record_id: str, limit: str,"
            f" window_seconds: str):"
        ),
        (
            f"    return client.eval(RATE_LIMIT_SCRIPT_{suffix}, 1,"
            f" f'{entity}:{{record_id}}:limit', limit, window_seconds)"
        ),
        "",
        "",
    ]


def _py_pubsub_block(entity: str, suffix: int) -> list[str]:
    return [
        "",
        f"def broadcast_{entity}_{suffix}_event(record_id: str, payload: str) -> None:",
        (
            f"    client.publish(f'events:{entity}', json.dumps("
            f"{{'id': record_id, 'payload': payload}}))"
        ),
        "",
        "",
        f"def watch_{entity}_{suffix}_events(handler) -> None:",
        "    pubsub = client.pubsub()",
        f"    pubsub.subscribe(f'events:{entity}')",
        "    for message in pubsub.listen():",
        "        if message['type'] == 'message':",
        "            handler(message['data'])",
        "",
        "",
    ]


def _py_one_hop_block(entity: str, suffix: int) -> list[str]:
    return [
        "",
        f"def fetch_{entity}_{suffix}_through_cache(record_id: str):",
        f"    return client.get(f'{entity}:{{record_id}}')",
        "",
        "",
    ]


def _py_fstring_composition_block(entity: str, suffix: int) -> list[str]:
    return [
        "",
        f"def load_{entity}_{suffix}_shard(record_id: str, shard: int):",
        f"    return client.get(f'{entity}:{{record_id}}:shard:{{shard}}')",
        "",
        "",
    ]


_PY_PATTERN_BLOCK_BUILDERS: dict[str, Callable[[str, int], list[str]]] = {
    "pipeline": _py_pipeline_block,
    "lua_script": _py_lua_block,
    "pubsub": _py_pubsub_block,
    "one_hop_wrapper": _py_one_hop_block,
    "fstring_composition": _py_fstring_composition_block,
}
