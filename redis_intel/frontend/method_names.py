"""The Redis client method vocabulary and construction names (PLAN 1.4).

PLAN section 1.4 command table: the complete documented client method
vocabulary of ioredis and node-redis v4/v5, normalized to lowercase with
spaces removed (ioredis exposes lowercase forms, node-redis camelCase, so a
callsite's method text is lowercased before lookup). A method on an
unresolvable receiver is recorded as an unresolved entry by
iter_unresolved_redis_method_calls when the method name plausibly names a
Redis command, so dynamic-receiver Redis calls are never silently dropped
(AC-12); C-2 decides the op kind or UNKNOWN. Deliberately excluded generic
names that collide with pervasive non-Redis JavaScript APIs: "call"
(Function.prototype.call) and "debug" (console/debugger methods).

The vocabulary frozenset is split across ``method_names_data.py`` and
``method_names_server.py`` so that neither module exceeds the rule-8 module
length; ``REDIS_METHOD_NAMES`` is their union and is therefore exactly the
single frozenset it replaced.
"""

from redis_intel.frontend.method_names_data import REDIS_DATA_METHOD_NAMES
from redis_intel.frontend.method_names_server import REDIS_SERVER_METHOD_NAMES

REDIS_METHOD_NAMES = REDIS_DATA_METHOD_NAMES | REDIS_SERVER_METHOD_NAMES

# and node-redis v4/v5 `createClient()` / `createCluster()`. Contract rev 3
# section 3.4 R1 adds `new IORedis(...)` as an equivalent ioredis construction.
IOREDIS_CONSTRUCTOR_NAMES = frozenset({"Redis", "IORedis"})

# Contract rev 3 section 3.4 R2: type annotations that name a Redis client
# type (including their generic forms, whose base name is matched).
REDIS_CLIENT_TYPE_ANNOTATIONS = frozenset({
    "Redis",
    "IORedis",
    "RedisClientType",
    "Cluster",
})

NODE_REDIS_FACTORY_NAMES = frozenset({"createClient", "createCluster"})
IOREDIS_PACKAGE_NAME = "ioredis"
NODE_REDIS_PACKAGE_NAME = "redis"

# Contract rev 3 section 3.4 R4: modules whose `require(...)` result is treated
# as an import binding equivalent to a static import.
REQUIRE_ACQUIRED_PACKAGES = frozenset({IOREDIS_PACKAGE_NAME, NODE_REDIS_PACKAGE_NAME})
