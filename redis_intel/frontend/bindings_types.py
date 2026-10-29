"""Value types shared by the client-binding mixins.

``_ClientBindings`` (in ``iterators.py``) composes its recording and
resolution behaviour from the mixins in ``bindings_fields``,
``bindings_imports``, ``bindings_factories``, ``bindings_packages`` and
``bindings_resolution``; the immutable records those mixins store are defined
here so none of them has to import another mixin module.
"""

from dataclasses import dataclass

from tree_sitter import Node

# Class-field binding kinds for the rev 3 section 3.4 receiver resolution.
_CLASS_FIELD_KIND_CONSTRUCTION = "construction"  # R1 (DEPTH 0)
_CLASS_FIELD_KIND_INJECTION = "injection"  # R2 (DEPTH 1)
_CLASS_FIELD_KIND_FACTORY = "factory"  # R3 (DEPTH 1 + inner DEPTH)
_CLASS_FIELD_KIND_ALIAS = "alias"  # rev-2 one-hop alias


@dataclass(frozen=True)
class _ClassFieldBinding:
    """How one class field (`this.<field>`) binds to a Redis client.

    ``construction_hint`` is the construction name for R1 (e.g. ``Redis``,
    ``createClient``), respectively the type-annotation base name for R2
    (e.g. ``RedisClientType``); ``factory_name``/``alias_target`` name the
    in-file factory function respectively the local the field was bound from.
    """

    kind: str
    construction_hint: str | None = None
    factory_name: str | None = None
    alias_target: str | None = None


@dataclass(frozen=True)
class _FactoryDefinition:
    """An in-file function whose returned expression may bind a receiver (R3).

    ``class_key`` is the stable byte-span key of the enclosing class for
    method factories (so a returned ``this.<field>`` resolves against that
    class's fields), otherwise ``None`` for module-level functions.
    """

    return_node: Node | None
    class_key: tuple[int, int] | None
