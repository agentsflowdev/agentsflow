"""Filesystem helpers for managing temporary git resources."""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

WORKTREE_PREFIX = "temporal-worktree-"
CLONE_PREFIX = "temporal-worktree-repo-"


def _resolve(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def is_managed_temp_dir(
    path: Path | str,
    prefixes: Iterable[str] = (WORKTREE_PREFIX,),
) -> bool:
    """Return True if path is under the system temp dir and matches prefixes."""

    prefixes = tuple(prefixes)
    if not prefixes:
        return False

    resolved = _resolve(path)
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        resolved.relative_to(temp_root)
    except ValueError:
        return False

    return any(resolved.name.startswith(prefix) for prefix in prefixes)


def safe_remove_tree(
    path: Path | str,
    *,
    reason: str,
    logger: logging.Logger | None = None,
    prefixes: Iterable[str] = (WORKTREE_PREFIX,),
) -> bool:
    """Remove a directory only when it matches our managed temp prefixes."""

    log = logger or logging.getLogger(__name__)
    target = Path(path).expanduser()
    if not target.exists():
        log.debug(
            "Skip deleting non-existent path",
            extra={"path": str(target), "reason": reason},
        )
        return False

    if not is_managed_temp_dir(target, prefixes=prefixes):
        log.warning(
            "Skipped deleting unmanaged directory",
            extra={"path": str(target), "reason": reason},
        )
        return False

    shutil.rmtree(target, ignore_errors=True)
    log.info(
        "Removed managed temporary directory",
        extra={"path": str(target), "reason": reason},
    )
    return True


__all__ = [
    "WORKTREE_PREFIX",
    "CLONE_PREFIX",
    "is_managed_temp_dir",
    "safe_remove_tree",
]
