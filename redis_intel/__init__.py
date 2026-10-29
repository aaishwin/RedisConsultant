"""Redis Engineering Intelligence Runtime.

Subpackages:
- ``redis_intel.frontend``: C-1 tree-sitter frontend producing ``ParseResult``
  (contract ``ir-boundary`` section 3).
- ``redis_intel.ir``: C-2 IR builder consuming ``ParseResult`` (section 4).
- ``redis_intel.governance``: C-7 connection-config redaction seam (section 6).

This top-level package deliberately re-exports nothing: each consumer imports
its surface from the owning subpackage, so parallel work on the three
subpackages never collides at this module.
"""
