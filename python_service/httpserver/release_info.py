"""Baked candidate identity; release staging replaces this module in its copy.

The running Python process imports this value once. Repository HEAD or a disk
manifest alone is never evidence that a service has loaded a release.
"""

try:
    from ._build_identity import RELEASE_ID, SOURCE_COMMIT, SOURCE_TREE_SHA256
except ModuleNotFoundError as exc:
    if exc.name != __package__ + "._build_identity":
        raise
    RELEASE_ID = "UNFROZEN_WORKTREE"
    SOURCE_COMMIT = "UNFROZEN_WORKTREE"
    SOURCE_TREE_SHA256 = "UNFROZEN_WORKTREE"
RELEASE_LAYOUT_VERSION = "6c-v1"
