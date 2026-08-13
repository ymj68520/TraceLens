"""
Evidence path canonicalization.

This module holds the single source of truth for normalizing a path into its
canonical Evidence-identity form. The rules below are FROZEN and back the
``file:<normalized_path>`` Evidence identity contract — do not change them
without updating that contract.

Frozen rules:
  - backslash -> forward slash
  - collapse repeated separators
  - strip trailing separator (root "/" is preserved)
  - NO lowercasing
  - NO normcase
  - NO dot-segment resolution
  - NO whitespace stripping

The function deliberately does NOT use ``os.path.normpath`` / ``Path.resolve`` /
``os.path.normcase`` / ``str.lower``: Evidence identity normalization must not
become host-OS filesystem normalization.
"""

import re

# Pre-compiled: collapse runs of "/" produced after backslash replacement.
_MULTI_SLASH = re.compile(r"/+")


def normalize_evidence_path(path: str) -> str:
    """Canonicalize a path for Evidence identity comparison.

    Args:
        path: Raw path string (may use backslashes, duplicate separators, or a
            trailing separator). ``None`` and empty string are accepted.

    Returns:
        The canonical form per the frozen rules above. ``None`` / empty -> "".
        The root path "/" is preserved.

    Notes:
        Idempotent on already-canonical paths: a normal-flow path that comes
        from ``SELECT path`` (already "/"-style) is returned unchanged, so
        callers that previously stored the raw form are not affected in the
        common case — only backslash / duplicate-separator inputs are aligned.
    """
    if not path:
        return ""
    p = path.replace("\\", "/")
    p = _MULTI_SLASH.sub("/", p)
    if len(p) > 1 and p.endswith("/"):
        p = p.rstrip("/")
    return p or "/"
