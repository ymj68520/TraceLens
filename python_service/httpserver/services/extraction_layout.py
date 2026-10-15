"""Task extraction-directory resolution.

Task metadata always records ``extraction_directory = <task_dir>/extracted_files``,
but the platform analyzers write their extracted copies to
``<stem>_extracted_files`` next to their per-OS database (e.g.
``linux_extracted_files`` for linux.db, ``oss_extracted_files`` for the OSS
analyzer). Path consumers that join a recorded extraction_directory with an
image path therefore miss the files on platform-analyzed images.

``candidate_roots`` yields every plausible extraction root for a task, recorded
directory first, so callers can probe them in order instead of hardcoding the
metadata path.
"""

from pathlib import Path

# Ordered by likelihood: platform analyzers first, then the plain default.
_KNOWN_STEMS = ("linux", "windows", "oss", "android")


def candidate_roots(extraction_dir) -> list:
    """Return plausible extraction roots for a recorded extraction_directory.

    The recorded directory always comes first when it exists. When it does not
    exist on disk, sibling ``*_extracted_files`` directories follow, known
    analyzer stems before unknown ones.
    """
    if not extraction_dir:
        return []
    recorded = Path(extraction_dir)
    if recorded.is_dir():
        return [recorded]
    parent = recorded.parent
    if not parent.is_dir():
        return [recorded]
    siblings = [p for p in parent.iterdir() if p.is_dir() and p.name.endswith("_extracted_files")]
    known_first = sorted(
        siblings,
        key=lambda p: (
            _KNOWN_STEMS.index(p.name.rsplit("_extracted_files", 1)[0])
            if p.name.rsplit("_extracted_files", 1)[0] in _KNOWN_STEMS
            else len(_KNOWN_STEMS),
            p.name,
        ),
    )
    return [recorded, *known_first]


def resolve_relative_path(extraction_dir, relative_path: str):
    """Resolve an image-internal path under a task's extraction roots.

    Returns the host path as a string, or None when no root contains the file.
    Rejects ``..`` traversal the same way ``resolve_analysis_path`` does.
    """
    if not extraction_dir or not relative_path:
        return None
    relative = str(relative_path).lstrip("/")
    if not relative or ".." in Path(relative).parts:
        return None
    for root in candidate_roots(extraction_dir):
        candidate = root / relative
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None
