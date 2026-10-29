"""Block builders split out of evaltools/corpus/content_ts.py (style contract rule 8).

Pure functions over seed/stream arguments; no clock, randomness or I/O. The
assembler in the original module re-imports these names; behaviour is unchanged.
"""


from evaltools.corpus.content import (
    EscalationSpec,
    locate_span,
)
from evaltools.corpus.prng import derive_int


def _ts_wrapper_depth_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[EscalationSpec]]:
    """Three-hop wrapper chain around the client (wrapper_depth_exceeded)."""
    suffix = derive_int(seed, f"{stream}:escalation", 0, 1000)
    inner_statement = f"return client.get(`{entity}:${{id}}`);"
    block = [
        (
            f"export function make{entity.capitalize()}OuterResolver{suffix}(id:"
            f" string) {{"
        ),
        "  return function resolveMiddle() {",
        "    return function resolveInner() {",
        f"      {inner_statement}",
        "    };",
        "  };",
        "}",
        "",
    ]
    specs = [
        EscalationSpec(
            reason_code="wrapper_depth_exceeded",
            span=locate_span(block, 3, inner_statement),
        )
    ]
    return block, specs


def _ts_dynamic_construction_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[EscalationSpec]]:
    """Key namespace from an environment variable at runtime (dynamic_construction)."""
    capitalized = entity.capitalize()
    suffix = derive_int(seed, f"{stream}:escalation", 0, 1000)
    dynamic_statement = "const dynamicKey = `${namespacePrefix}:{entity}:${id}`;"
    block = [
        'const namespacePrefix = process.env.CACHE_NAMESPACE ?? "fallback";',
        "",
        (
            f"export async function loadDynamic{capitalized}{suffix}(id: string):"
            f" Promise<string | null> {{"
        ),
        f"  {dynamic_statement}",
        "  return client.get(dynamicKey);",
        "}",
        "",
    ]
    specs = [
        EscalationSpec(
            reason_code="dynamic_construction",
            span=locate_span(block, 3, dynamic_statement),
        )
    ]
    return block, specs


def _ts_unresolvable_expression_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[EscalationSpec]]:
    """Key template returned by a policy lookup: statically unresolvable expression."""
    capitalized = entity.capitalize()
    suffix = derive_int(seed, f"{stream}:escalation", 0, 1000)
    key_call = "return client.get(resolveKeyFromPolicy(id));"
    block = [
        "const keyPolicyTable: Record<string, string> = {};",
        "",
        "function resolveKeyFromPolicy(id: string): string {",
        f"  return keyPolicyTable[id] ?? `{entity}:${{id}}`;",
        "}",
        "",
        (
            f"export async function load{capitalized}{suffix}ViaPolicy(id: string):"
            f" Promise<string | null> {{"
        ),
        f"  {key_call}",
        "}",
        "",
    ]
    specs = [
        EscalationSpec(
            reason_code="unresolvable_expression", span=locate_span(block, 7, key_call)
        )
    ]
    return block, specs


def _ts_unsupported_syntax_block(
    entity: str, seed: int, stream: str
) -> tuple[list[str], list[EscalationSpec]]:
    """Pathologically nested parenthesisation no bounded parser budget accepts."""
    del entity  # the pathological line is entity-independent
    nesting_depth = 200 + derive_int(seed, f"{stream}:depth", 0, 100)
    deep_line = (
        f"const deeplyNestedValue = {'(' * nesting_depth}seedValue"
        f"{')' * nesting_depth};"
    )
    block = [deep_line, ""]
    specs = [
        EscalationSpec(
            reason_code="unsupported_syntax",
            span=locate_span(block, 0, "const deeplyNestedValue"),
        )
    ]
    return block, specs
