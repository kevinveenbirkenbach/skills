from __future__ import annotations

import os
from pathlib import Path


def sealed(directory: Path) -> bool:
    try:
        stats = [part.stat() for part in (directory, *directory.parents)]
    except OSError:
        return False
    me = os.getuid()
    return all((st.st_uid != me or st.st_uid == 0) and not st.st_mode & 0o022 for st in stats)


def trusted(path: str) -> str:
    """Filter a PATH value.

    Args:
      path: the PATH value, os.pathsep-separated.

    Returns:
      The real paths of its directories that, with every parent, belong to
      root or another uid and that neither group nor others can write, in
      their order.
    """
    kept: list[str] = []
    for entry in filter(None, path.split(os.pathsep)):
        try:
            real = Path(entry).resolve(strict=True)
        except OSError:
            continue
        if sealed(real) and str(real) not in kept:
            kept.append(str(real))
    return os.pathsep.join(kept)
