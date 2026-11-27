#!/usr/bin/env python3
"""Pre-bash entry of kvb-code-review for hooks.py.

Returns:
    0 at once for every command that names no operator.py row with a push
    word; otherwise review.py's hook verdict on the same event.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

REVIEW = Path(__file__).resolve().with_name("review.py")
ROW = "operator.py"
PUSH_WORDS = ("push", "gipsn")


def main() -> int:
    raw = sys.stdin.read()
    if ROW not in raw or not any(word in raw for word in PUSH_WORDS):
        return 0
    spec = importlib.util.spec_from_file_location("kvb_review_hook_full", REVIEW)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.stdin, sys.argv = io.StringIO(raw), [str(REVIEW), "hook"]
    return module.main()


if __name__ == "__main__":
    sys.exit(main())
